"""Read outcomes preserve original intent and never create publication authority."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_journal_production import synthetic_candidate

from finai_api.services.entity_movement_review import digest
from finai_api.services.journal_production import compile_row
from finai_api.services.journal_production_dispositions import compile_dispositions
from finai_api.services.workspace import WorkspaceError


def case():
    pair, source, targets, request = synthetic_candidate()
    row, proposal = compile_row(pair, source, targets, request, "test")
    row.update(state="ELIGIBLE_FOR_REVIEW", proposal=proposal.model_dump(mode="json"))
    manifest = {
        "contract": "source-journal-production/1",
        "request": request.model_dump(mode="json"),
        "source_sha256": source["sha256"],
        "binding": source["binding"],
        "rows": [row],
        "submitted": [
            {"coordinate": "Base!S2", "proposal_id": str(proposal.proposal_id), "decision": None}
        ],
    }
    detail = SimpleNamespace(
        proposal=proposal,
        decision="APPROVED",
        submitted_by="maker",
        reviewed_by="checker",
        review_rationale="Independent synthetic review",
        recorded_at=None,
    )
    versions = [
        {
            "resource_id": str(m.resource_id),
            "version_id": str(uuid4()),
            "content_hash": "a" * 64,
            "proposal_id": str(proposal.proposal_id),
            "object_type": m.object_type,
            "attributes": m.model_dump(mode="json")["attributes"],
            "authority_state": "APPROVED",
        }
        for m in proposal.mutations
    ]
    return manifest, request, detail, versions


def run(data, *, unavailable=False):
    manifest, request, detail, versions = data
    manifest["receipt_hash"] = digest({k: v for k, v in manifest.items() if k != "receipt_hash"})

    def proposal(_):
        if unavailable:
            raise WorkspaceError(404, "Unavailable")
        return detail

    return compile_dispositions(
        manifest, request.request_id, request.company_id, proposal, lambda _: versions
    )


def test_current_approval_and_partial_outcomes_preserve_immutable_receipt():
    data = case()
    manifest, _, _, _ = data
    manifest["request"]["coordinates"] += ["Base!S288", "Base!S17"]
    manifest["rows"] += [
        {
            "coordinate": "Base!S288",
            "state": "EXCLUDED",
            "blockers": [{"code": "MISSING_LITERAL_POSTED_AMOUNT"}],
        },
        {
            "coordinate": "Base!S17",
            "state": "BLOCKED",
            "blockers": [{"code": "EXACT_AMOUNT_CONTRACT_UNSUPPORTED"}],
        },
    ]
    result = run(data)
    retained = deepcopy(manifest)
    assert result["selection_count"] == 3
    assert result["counts"] == {"BLOCKED": 1, "EXCLUDED": 1, "PUBLISHED": 1}
    assert len(result["items"][0]["publication"]["lines"]) == 2
    assert result["financial_totals"] is None and not result["current_use_authorized"]
    assert result["source_exclusions"][0]["coordinate"] == "Base!S288"
    run(data)
    assert manifest == retained and manifest["submitted"][0]["decision"] is None


@pytest.mark.parametrize(
    "decision,state",
    [(None, "PENDING_REVIEW"), ("REJECTED", "REJECTED"), ("APPROVED", "PUBLISHED")],
)
def test_crash_before_submitted_receipt_still_observes_real_proposal(decision, state):
    data = case()
    del data[0]["submitted"]
    data[2].decision = decision
    assert run(data)["items"][0]["state"] == state


def test_missing_proposal_is_not_misreported_as_pending_or_success():
    data = case()
    assert run(data, unavailable=True)["items"][0]["state"] == "UNAVAILABLE"
    del data[0]["submitted"]
    assert run(data, unavailable=True)["items"][0]["state"] == "NOT_SUBMITTED"


@pytest.mark.parametrize(
    "failure", ["missing_line", "changed_amount", "other_proposal", "duplicate_version"]
)
def test_approved_decision_without_exact_bundle_is_unavailable(failure):
    data = case()
    versions = data[3]
    if failure == "missing_line":
        versions.pop()
    elif failure == "changed_amount":
        versions[-1]["attributes"]["amount"]["amount"] = "999.00"
    elif failure == "other_proposal":
        versions[-1]["proposal_id"] = str(uuid4())
    else:
        versions.append(deepcopy(versions[-1]))
    result = run(data)
    assert result["items"][0]["state"] == "UNAVAILABLE"
    assert result["items"][0]["publication"] is None


def test_wrong_company_tampered_receipt_and_changed_proposal_fail_closed():
    data = case()
    manifest, request, detail, versions = data
    run(data)
    with pytest.raises(WorkspaceError, match="company"):
        compile_dispositions(
            manifest, request.request_id, uuid4(), lambda _: detail, lambda _: versions
        )
    manifest["source_sha256"] = "b" * 64
    with pytest.raises(WorkspaceError, match="integrity"):
        compile_dispositions(
            manifest, request.request_id, request.company_id, lambda _: detail, lambda _: versions
        )
    detail.proposal = detail.proposal.model_copy(update={"title": "Changed original intent"})
    with pytest.raises(WorkspaceError, match="differs from retained"):
        run(data)


def test_reader_uses_prepared_fallback_and_only_selects_exact_proposal_versions(monkeypatch):
    from contextlib import nullcontext
    from finai_api.services import journal_production_dispositions as service

    data = case()
    manifest, request, detail, versions = data
    run(data)
    calls = []

    def history(principal, identity, phase="SUBMITTED"):
        calls.append(phase)
        assert identity == request.request_id
        return manifest if phase == "PREPARED" else None

    monkeypatch.setattr(service.journal_production_history, "history", history)
    monkeypatch.setattr(service.resources, "proposal_detail", lambda *_: detail)
    canonical = [
        {
            **v,
            "identity_key": v["resource_id"],
            "display_name": "Synthetic journal item",
            "access_entity": "test",
            "schema_version_id": None,
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": None,
            "system_from": "2026-01-01T00:00:00Z",
            "evidence_class": "USER_ASSERTED",
        }
        for v in versions
    ]
    principal = SimpleNamespace(
        permissions=["ontology_read"], scope=SimpleNamespace(tenant_id=uuid4())
    )

    class Cursor:
        def execute(self, sql, args):
            assert sql.startswith("SELECT") and args == (
                principal.scope.tenant_id,
                detail.proposal.proposal_id,
            )
            return self

        def fetchall(self):
            return canonical

    conn = SimpleNamespace(cursor=lambda **_: nullcontext(Cursor()))
    monkeypatch.setattr(service.resources, "resource_connection", lambda _: nullcontext(conn))
    result = service.read(principal, request.request_id, request.company_id)
    assert calls == ["SUBMITTED", "PREPARED"] and result["counts"] == {"PUBLISHED": 1}
    assert result["consistency"] == "PER_ITEM_READ_OBSERVATION"
    assert result["receipt_hash"] == digest(
        {k: v for k, v in result.items() if k != "receipt_hash"}
    )
    monkeypatch.setattr(service.journal_production_history, "history", lambda *_: None)
    with pytest.raises(WorkspaceError, match="exact scope"):
        service.read(principal, request.request_id, request.company_id)


@pytest.mark.parametrize(
    "failure",
    [
        "contract",
        "duplicate_row",
        "unknown_selection",
        "missing_proposal",
        "wrong_company",
        "wrong_proposal_id",
        "malformed",
        "unknown_decision",
    ],
)
def test_inconsistent_disposition_evidence_never_becomes_a_success(failure):
    data = case()
    manifest, _, detail, _ = data
    row = manifest["rows"][0]
    if failure == "contract":
        manifest["contract"] = "other/1"
    elif failure == "duplicate_row":
        manifest["rows"].append(deepcopy(row))
    elif failure == "unknown_selection":
        manifest["request"]["coordinates"].append("Base!S9999")
    elif failure == "missing_proposal":
        del row["proposal"]
    elif failure == "wrong_company":
        next(m for m in row["proposal"]["mutations"] if m["object_type"] == "JournalEntry")[
            "attributes"
        ]["legal_entity_id"] = str(uuid4())
    elif failure == "wrong_proposal_id":
        row["proposal"]["proposal_id"] = str(uuid4())
    elif failure == "malformed":
        del manifest["request"]
    else:
        detail.decision = "UNKNOWN"
    with pytest.raises(WorkspaceError):
        run(data)

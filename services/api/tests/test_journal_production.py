"""Production intent, exact bundles and durable retry contracts; synthetic eligibility."""
# ruff: noqa: F811

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_entity_movement_review import fixture
from test_semantic_entity_movements import case as workspace_case  # noqa: F401
from test_source_journal_compatibility import compatibility_case

from finai_api.domain.journal_production import JournalProductionRequest, SidePolicies
from finai_api.domain.resources import ResourceReview
from finai_api.services import journal_production as service
from finai_api.services import journal_production_history as retention
from finai_api.services.entity_movement_review import digest, review
from finai_api.services.workspace import WorkspaceError


def request(company):
    return JournalProductionRequest(
        request_id=uuid4(),
        invocation_id=uuid4(),
        company_id=company,
        effective_at=datetime.now(UTC),
        rationale="Review exact retained posting",
        coordinates=["Base!S2"],
    )


def synthetic_candidate():
    parsed, source, targets, ids = fixture()
    source["evidence"] = {"resource_id": str(uuid4()), "version_id": str(uuid4())}
    for ref in source["accounts"].values():
        node = targets.pop(ref["resource_id"])
        ref.update(resource_id=str(uuid4()), version_id=str(uuid4()))
        node.update(ref)
        targets[ref["resource_id"]] = node
    for key, node in targets.items():
        node.setdefault("resource_id", key)
        node.setdefault("version_id", str(uuid4()))
    targets[ids["scope"]]["attributes"].update(
        source_profile="1c_journal", evidence_id=source["evidence"]["resource_id"]
    )
    req = request(ids["company"])
    dims = {
        "contract": "journal-line-dimensions/1",
        "policy": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
        "assignments": [],
    }
    req = req.model_copy(update={"policies": {"Base!S2": SidePolicies(debit=dims, credit=dims)}})
    pair = review(parsed, source, targets, {})["pairs"][0]
    return pair, source, targets, req


def test_compiled_bundle_preserves_exact_source_and_requires_shared_validation():
    pair, source, targets, req = synthetic_candidate()
    row, proposal = service.compile_row(pair, source, targets, req, "synthetic")
    assert row["state"] == "CANDIDATE"  # The compiler alone cannot grant eligibility.
    assert [m.object_type for m in proposal.mutations] == [
        "SourceRecord",
        "JournalEntry",
        "JournalLine",
        "JournalLine",
    ]
    record, entry, debit, credit = proposal.mutations
    assert record.attributes["coordinate"] == "Base!S2"
    assert debit.attributes["amount"] == credit.attributes["amount"] == pair["lines"][0]["amount"]
    assert {debit.attributes["side"], credit.attributes["side"]} == {"DEBIT", "CREDIT"}
    assert (
        debit.attributes["journal_id"] == credit.attributes["journal_id"] == str(entry.resource_id)
    )
    assert debit.attributes["source_record_id"] == str(record.resource_id)
    assert proposal == service.compile_row(pair, source, targets, req, "synthetic")[1]
    assert proposal.source_versions[entry.resource_id]


def test_missing_side_authority_is_never_an_implicit_empty_policy():
    pair, source, targets, req = synthetic_candidate()
    row, proposal = service.compile_row(
        pair, source, targets, req.model_copy(update={"policies": {}}), "test"
    )
    assert proposal is None
    assert [b["required_authority"]["side"] for b in row["blockers"]] == ["DEBIT", "CREDIT"]


def test_existing_source_record_reuse_preserves_reviewed_dimension_provenance():
    from finai_api.domain.resource_lifecycle import VersionReference

    pair, source, targets, req = synthetic_candidate()
    reference = VersionReference(resource_id=uuid4(), version_id=uuid4())
    targets[str(reference.resource_id)] = {
        **reference.model_dump(mode="json"),
        "object_type": "SourceRecord",
        "authority_state": "APPROVED",
        "evidence_class": "SOURCE_BOUND",
        "attributes": {"evidence_id": source["evidence"]["resource_id"], "coordinate": "Base!S2"},
    }
    req.policies["Base!S2"] = req.policies["Base!S2"].model_copy(
        update={"source_record": reference}
    )
    _, proposal = service.compile_row(pair, source, targets, req, "test")
    assert len(proposal.mutations) == 3
    assert all(
        m.attributes["source_record_id"] == str(reference.resource_id)
        for m in proposal.mutations
        if m.object_type == "JournalLine"
    )
    targets[str(reference.resource_id)]["attributes"]["coordinate"] = "Base!S288"
    row, proposal = service.compile_row(pair, source, targets, req, "test")
    assert proposal is None and row["blockers"][0]["code"] == "EXACT_SOURCE_RECORD_REQUIRED"


def test_source_profile_refusal_names_required_reviewed_scope():
    parsed, source, targets, ids = fixture()
    pair = review(parsed, source, targets, {})["pairs"][0]
    row, proposal = service.compile_row(pair, source, targets, request(ids["company"]), "test")
    assert proposal is None
    assert row["blockers"][0]["code"] == "SOURCE_JOURNAL_SEMANTICS_UNSUPPORTED"
    assert row["blockers"][0]["required_authority"]["resource_id"] == source["scope"]["resource_id"]


def test_preview_refuses_unsupported_source_without_any_proposal_write(workspace_case, monkeypatch):
    _history, original = workspace_case
    req = request(original.company_id).model_copy(update={"invocation_id": original.invocation_id})
    p = SimpleNamespace(
        permissions=["ontology_propose"], scope=SimpleNamespace(legal_entity_id="test")
    )
    monkeypatch.setattr(
        service.resources, "propose", lambda *_: pytest.fail("Preview wrote a proposal")
    )
    manifest, proposals = service.prepare(p, req)
    assert not proposals and manifest["published_journal_count"] == 0
    assert all(row["state"] == "BLOCKED" for row in manifest["rows"])
    with pytest.raises(WorkspaceError):
        service.prepare(p, req.model_copy(update={"coordinates": ["Base!S99999"]}))


def test_retained_receipt_rejects_mutation_and_request_reuse():
    req = request(uuid4())
    p = SimpleNamespace(actor_id="maker")
    manifest = {"contract": "source-journal-production/1", "rows": []}
    manifest["receipt_hash"] = digest(manifest)
    row = {
        "payload": manifest,
        "receipt_hash": manifest["receipt_hash"],
        "actor_id": "maker",
        "request_hash": digest(req.model_dump(mode="json")),
    }
    assert retention.verify(row, p, req) == manifest
    with pytest.raises(WorkspaceError, match="different intent"):
        retention.verify(row, p, req.model_copy(update={"rationale": "Another accounting intent"}))
    row["payload"]["rows"].append({"state": "ELIGIBLE"})
    with pytest.raises(WorkspaceError, match="integrity"):
        retention.verify(row, p, req)


def test_crash_resume_uses_retained_proposal_and_no_second_submission(monkeypatch):
    pair, source, targets, req = synthetic_candidate()
    row, proposal = service.compile_row(pair, source, targets, req, "test")
    row["proposal"] = proposal.model_dump(mode="json")
    manifest = {"contract": "source-journal-production/1", "rows": [row]}
    manifest["receipt_hash"] = digest(manifest)
    stored = {"PREPARED": manifest}
    monkeypatch.setattr(
        retention,
        "history",
        lambda p, i, phase="SUBMITTED", request=None: deepcopy(stored.get(phase)),
    )

    def retain(p, r, phase, m):
        stored[phase] = deepcopy(m)
        return m

    monkeypatch.setattr(retention, "retain", retain)
    monkeypatch.setattr(
        service, "prepare", lambda *_: pytest.fail("Lost immutable prepared intent")
    )
    calls = []

    def propose(p, submitted):
        calls.append(submitted)
        return SimpleNamespace(proposal=submitted, decision=None)

    monkeypatch.setattr(service.resources, "propose", propose)
    p = SimpleNamespace(permissions=["ontology_propose"])
    first = service.submit(p, req)
    assert service.submit(p, req) == first and calls == [proposal]


def test_checker_uses_existing_review_guard_without_bypassing_maker(monkeypatch):
    pair, source, targets, req = synthetic_candidate()
    _, proposal = service.compile_row(pair, source, targets, req, "test")
    monkeypatch.setattr(
        service.resources, "proposal_detail", lambda *_: SimpleNamespace(proposal=proposal)
    )

    def refuse(*_):
        raise WorkspaceError(403, "Separate maker/checker required")

    monkeypatch.setattr(service.resources, "review", refuse)
    with pytest.raises(WorkspaceError, match="Separate maker"):
        service.check(
            SimpleNamespace(permissions=["ontology_review"]),
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Independent journal review"),
        )


def test_request_cannot_supply_amounts_or_duplicate_rows():
    value = request(uuid4()).model_dump(mode="json")
    with pytest.raises(ValueError):
        JournalProductionRequest.model_validate({**value, "amount": "999"})
    with pytest.raises(ValueError):
        JournalProductionRequest.model_validate({**value, "coordinates": ["Base!S2", "Base!S2"]})


def test_compatibility_compiler_preserves_family_and_refuses_stale_or_wrong_cell():
    from finai_api.domain.resource_lifecycle import VersionReference

    pair, source, targets, req = synthetic_candidate()
    authority, _, _, _ = compatibility_case(source, targets)
    ref = VersionReference(resource_id=authority.resource_id, version_id=uuid4())
    targets[str(ref.resource_id)] = {
        **ref.model_dump(mode="json"),
        "object_type": "SourceJournalCompatibility",
        "authority_state": "APPROVED",
        "evidence_class": "USER_ASSERTED",
        "attributes": authority.attributes,
    }
    req = req.model_copy(update={"compatibility": ref})
    result, proposal = service.compile_row(pair, source, targets, req, "test")
    assert result["state"] == "CANDIDATE" and proposal is not None, result
    authority.attributes["definition"]["amount_column"] = "AD"
    result, proposal = service.compile_row(pair, source, targets, req, "test")
    assert proposal is None and result["blockers"][0]["code"] == "SOURCE_COMPATIBILITY_INVALID"
    targets[str(ref.resource_id)]["version_id"] = str(uuid4())
    result, proposal = service.compile_row(pair, source, targets, req, "test")
    assert proposal is None and "version changed" in result["blockers"][0]["detail"]


def test_preview_requires_canonical_guard_and_retains_missing_row(workspace_case, monkeypatch):
    from contextlib import nullcontext

    history, original = workspace_case
    req = request(original.company_id).model_copy(update={"invocation_id": original.invocation_id})
    p = SimpleNamespace(
        permissions=["ontology_propose"],
        scope=SimpleNamespace(legal_entity_id="test", tenant_id="test"),
    )
    pair, source, targets, candidate_request = synthetic_candidate()
    row, proposal = service.compile_row(pair, source, targets, candidate_request, "test")
    descriptor, _, _ = service.build(
        history, *service.semantic_analysis.load(p, original.invocation_id)[1:], original.company_id
    )
    monkeypatch.setattr(service, "build", lambda *_: (descriptor, [], {}))
    history["output"]["entity_movement_review"]["reconciliation"]["excluded_rows"] = [
        {"coordinate": "Base!S288", "row": 288, "reason": "MISSING_LITERAL_POSTED_AMOUNT"}
    ]
    monkeypatch.setattr(service, "compile_row", lambda *_: (deepcopy(row), proposal))
    monkeypatch.setattr(
        service.resources,
        "resource_connection",
        lambda *_: nullcontext(SimpleNamespace(execute=lambda *_: None)),
    )

    def refuse(*_):
        raise WorkspaceError(409, "Posting period is locked")

    monkeypatch.setattr(service.resources, "_validate", refuse)
    manifest, proposals = service.prepare(p, req)
    assert not proposals
    assert (
        next(r for r in manifest["rows"] if r["coordinate"] == "Base!S2")["blockers"][0]["code"]
        == "CANONICAL_PUBLICATION_GUARD_REFUSED"
    )
    assert (
        next(r for r in manifest["rows"] if r["coordinate"] == "Base!S288")["state"] == "EXCLUDED"
    )
    monkeypatch.setattr(service.resources, "_validate", lambda *_: None)
    manifest, proposals = service.prepare(p, req)
    assert proposals and manifest["advisory"] is True and manifest["published_journal_count"] == 0

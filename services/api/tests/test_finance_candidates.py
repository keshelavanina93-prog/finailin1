"""Finance intake keeps authentic source scope separate from pending publication."""

import io
import json
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from pydantic import ValidationError

from finai_api.domain.authority import ExactScope
from finai_api.domain.finance_candidates import CandidateIntakeRequest, CandidateVersionPin
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import finance_candidates as candidates
from finai_api.services.workspace import WorkspaceError

AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def intake(monkeypatch):
    principal = Principal(
        actor_id="synthetic-maker",
        display_name="Synthetic maker",
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="fixture-company-scope",
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose"),
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Accounts"
    sheet.append(["Код", "Наименование", "Субконто 1", "Субконто 2", "Акт.", "Вал."])
    rows = []
    for index in range(26):
        code, name = str(1400 + index), f"ანგარიში {index} / Account {index}"
        if index == 1:
            name += " // "
        sheet.append([code, name, "Контрагенты", "Договоры", "А", "Да"])  # noqa: RUF001
        rows.append(
            {
                "object_type": "LocalAccount",
                "identity_key": code,
                "display_name": name,
                "authority_state": "CANDIDATE",
                "epistemic": "OBSERVED",
                "attributes": {
                    "code": code,
                    "name": name,
                    "source_row": index + 2,
                    "subkonto_labels": ["Контрагенты", "Договоры"],
                    "nature": "А",  # noqa: RUF001
                    "currency_flag": True,
                },
            }
        )
    stream = io.BytesIO()
    workbook.save(stream)
    content = stream.getvalue()
    digest = sha256(content).hexdigest()
    construction = {
        "construction_id": "g8.candidate.coa-406",
        "status": "CANDIDATE",
        "not_catalog": True,
        "evidence": {"sha256": digest, "expected_sha256": digest, "hash_match": True},
        "mutations": rows,
    }
    state = SimpleNamespace(
        construction=construction,
        content=content,
        metadata={"source_sha256": digest},
        submitted=[],
        saved={},
        existing={},
    )
    objects = {}

    def resource(kind, attributes, identity=None, platform=False):
        identity = identity or uuid4()
        value = {
            "resource_id": str(identity),
            "version_id": str(uuid4()),
            "object_type": kind,
            "authority_state": "APPROVED",
            "evidence_class": "SOURCE_BOUND",
            "access_entity": "__PLATFORM__" if platform else principal.scope.legal_entity_id,
            "valid_from": AT.isoformat(),
            "valid_to": None,
            "attributes": attributes,
            "display_name": kind,
        }
        objects[identity] = value
        return CandidateVersionPin(resource_id=identity, version_id=value["version_id"])

    evidence = resource("SourceEvidence", {"sha256": digest, "source_system": "fixture"})
    company = resource("LegalEntity", {})
    chart = resource(
        "LocalChartOfAccounts", {"legal_entity_id": str(company.resource_id), "code": "fixture"}
    )
    resource(
        "LinkType",
        {"sources": ["*"], "targets": ["SourceRecord", "SourceEvidence"]},
        canonical_id(principal.scope.tenant_id, "LinkType", "DERIVED_FROM"),
        True,
    )
    request = CandidateIntakeRequest(
        construction_id="g8.candidate.coa-406",
        document_id="synthetic-document",
        evidence=evidence,
        company=company,
        chart=chart,
        valid_from=AT,
        rationale="Review synthetic retained evidence",
    )

    def get_resource(_principal, identity):
        if identity not in objects:
            raise WorkspaceError(404, "Fixture resource unavailable")
        return {"resource": objects[identity]}

    def detail(_principal, identity):
        if identity not in state.saved:
            raise WorkspaceError(404, "Fixture proposal unavailable")
        return state.saved[identity]

    def propose(actor, proposal):
        state.submitted.append((actor, proposal))
        item = SimpleNamespace(proposal=proposal, decision=None, submitted_by=actor.actor_id)
        state.saved[proposal.proposal_id] = item
        return item

    monkeypatch.setattr(candidates, "load_candidate_construction", lambda _: state.construction)
    monkeypatch.setattr(
        candidates,
        "candidate_construction_bytes",
        lambda _: json.dumps(state.construction).encode(),
    )
    monkeypatch.setattr(
        candidates.source_documents, "document_bytes", lambda *_: (state.metadata, state.content)
    )
    monkeypatch.setattr(candidates.resources, "get_resource", get_resource)
    monkeypatch.setattr(
        candidates.resources,
        "current_resources",
        lambda _, identities: {
            str(i): state.existing[str(i)] for i in identities if str(i) in state.existing
        },
    )
    monkeypatch.setattr(candidates.resources, "proposal_detail", detail)
    monkeypatch.setattr(candidates.resources, "propose", propose)
    monkeypatch.setattr(
        candidates.resources, "review", lambda *_: pytest.fail("Adapter must never review")
    )
    state.principal, state.request, state.objects, state.resource = (
        principal,
        request,
        objects,
        resource,
    )
    return state


def test_preview_reads_retained_workbook_preserves_labels_and_bounds_native_mutations(intake):
    plan = candidates.preview(intake.principal, intake.request)
    proposal = ResourceProposal.model_validate(plan["proposal"])
    assert plan["can_submit"] and plan["mutation_count"] == 100 and plan["next_offset"] == 25
    assert not intake.submitted
    assert plan["authority"] == "CANDIDATE_ONLY" and plan["review_required"]
    account = next(item for item in proposal.mutations if item.object_type == "LocalAccount")
    assert account.resource_id == uuid5(intake.request.chart.resource_id, "1400")
    assert account.attributes["account_code"] == "1400" and "code" not in account.attributes
    definition = next(
        item for item in proposal.mutations if item.object_type == "SourceAccountDefinition"
    )
    assert definition.attributes["source_name"] == "ანგარიში 0 / Account 0"
    raw = definition.attributes["definition"]
    assert raw["candidate"]["attributes"]["subkonto_labels"] == ["Контрагенты", "Договоры"]
    assert raw["observed"]["currency_tracking_source"] == "Да"
    assert raw["required_dimension_policy"] == "UNESTABLISHED"
    assert all(len(pins) <= 100 for pins in proposal.source_versions.values())


def test_raw_trailing_name_whitespace_survives_normalized_profile(intake):
    plan = candidates.preview(intake.principal, intake.request)
    definition = next(
        row for row in plan["proposal"]["mutations"]
        if row["object_type"] == "SourceAccountDefinition"
        and row["attributes"]["account_code"] == "1401"
    )
    source = definition["attributes"]
    assert source["source_name"].endswith(" // ")
    assert source["definition"]["observed"]["source_name"].endswith(" //")
    assert source["definition"]["observed"]["raw_source_name"].endswith(" // ")
    assert source["definition"]["candidate"]["display_name"] == source["source_name"]


@pytest.mark.parametrize("field", ["document_id", "evidence", "company", "chart"])
def test_missing_source_or_explicit_scope_blocks_every_write(intake, field):
    request = intake.request.model_copy(update={field: None})
    plan = candidates.preview(intake.principal, request)
    assert not plan["can_submit"] and plan["blockers"]
    with pytest.raises(WorkspaceError):
        candidates.submit(intake.principal, request)
    assert not intake.submitted


@pytest.mark.parametrize(
    "fault", ["document_hash", "evidence_hash", "source_pin", "client_boolean"]
)
def test_hash_match_is_computed_from_retained_bytes_not_client_flags(intake, fault):
    if fault == "document_hash":
        intake.metadata["source_sha256"] = "0" * 64
    elif fault == "evidence_hash":
        intake.objects[intake.request.evidence.resource_id]["attributes"]["sha256"] = "0" * 64
    else:
        intake.construction["evidence"]["sha256"] = "0" * 64
        if fault == "client_boolean":
            intake.construction["evidence"].update(expected_sha256="0" * 64, hash_match=True)
    plan = candidates.preview(intake.principal, intake.request)
    assert not plan["can_submit"] and any("hash" in b or "bytes" in b for b in plan["blockers"])
    assert not intake.submitted


@pytest.mark.parametrize(
    "fault", ["cross_scope", "chart_company", "stale", "revoked", "future", "template"]
)
def test_authorized_read_does_not_bypass_exact_scope_or_version_checks(intake, fault):
    chart = intake.objects[intake.request.chart.resource_id]
    if fault == "cross_scope":
        chart["access_entity"] = "different-company"
    elif fault == "chart_company":
        chart["attributes"]["legal_entity_id"] = str(uuid4())
    elif fault == "stale":
        chart["version_id"] = str(uuid4())
    elif fault == "revoked":
        chart["authority_state"] = "REVOKED"
    elif fault == "future":
        chart["valid_from"] = "2099-01-01T00:00:00+00:00"
    else:
        chart["evidence_class"] = "REFERENCE_TEMPLATE"
    plan = candidates.preview(intake.principal, intake.request)
    assert not plan["can_submit"] and plan["blockers"]


@pytest.mark.parametrize("fault", ["duplicate", "missing_code", "label_change", "analytic_change"])
def test_unresolved_rows_cannot_be_silently_dropped_from_submission(intake, fault):
    first = intake.construction["mutations"][0]
    if fault == "duplicate":
        intake.construction["mutations"].append(deepcopy(first))
    elif fault == "missing_code":
        first["attributes"]["code"] = ""
    elif fault == "label_change":
        first["attributes"]["name"] = "Invented name"
    else:
        first["attributes"]["subkonto_labels"] = ["Invented universal analytic"]
    plan = candidates.preview(intake.principal, intake.request)
    assert not plan["can_submit"] and plan["rows"][0]["blockers"]
    assert plan["rows"][0]["epistemic"] == "UNAVAILABLE"
    with pytest.raises(WorkspaceError):
        candidates.submit(intake.principal, intake.request)
    assert not intake.submitted


def test_submit_is_pending_native_review_and_retry_does_not_resubmit(intake):
    first = candidates.submit(intake.principal, intake.request)
    second = candidates.submit(intake.principal, intake.request)
    assert first["proposal_id"] == second["proposal_id"]
    assert first["created"] and not second["created"]
    assert first["decision"] is None and first["review_required"]
    assert len(intake.submitted) == 1 and intake.submitted[0][0] is intake.principal
    proposal = intake.submitted[0][1]
    assert proposal.access_entity == intake.principal.scope.legal_entity_id
    assert all(
        intake.request.chart.resource_id in refs for refs in proposal.source_versions.values()
    )


def test_changed_chart_and_actor_produce_separate_canonical_and_proposal_identities(intake):
    first = candidates.preview(intake.principal, intake.request)
    chart = intake.resource(
        "LocalChartOfAccounts",
        {"legal_entity_id": str(intake.request.company.resource_id), "code": "second"},
    )
    second = candidates.preview(
        intake.principal, intake.request.model_copy(update={"chart": chart})
    )
    assert first["proposal_id"] != second["proposal_id"]
    assert set(first["rows"][0]["planned_resource_ids"]) != set(
        second["rows"][0]["planned_resource_ids"]
    )
    other = intake.principal.model_copy(update={"actor_id": "other-maker"})
    assert candidates.preview(other, intake.request)["proposal_id"] != first["proposal_id"]


def test_partial_existing_page_limits_dependency_pins_and_refuses_conflicting_heads(intake):
    first = candidates.preview(intake.principal, intake.request)
    for mutation in first["proposal"]["mutations"][:-1]:
        intake.existing[mutation["resource_id"]] = {
            **mutation,
            "version_id": str(uuid4()),
            "access_entity": intake.principal.scope.legal_entity_id,
        }
    second = candidates.preview(intake.principal, intake.request)
    assert second["can_submit"] and second["mutation_count"] == 1
    assert all(len(pins) <= 7 for pins in second["proposal"]["source_versions"].values())
    next(iter(intake.existing.values()))["access_entity"] = "other"
    assert not candidates.preview(intake.principal, intake.request)["can_submit"]


def test_entity_retained_json_proves_assertions_without_ownership_or_legal_fact_authority(intake):
    row = {
        "object_type": "LegalEntity",
        "identity_key": "SYNTHETIC",
        "display_name": "Synthetic entity",
        "authority_state": "CANDIDATE",
        "attributes": {"parent_key": "UNVERIFIED", "role": "UNVERIFIED"},
    }
    intake.construction = {
        "construction_id": "g8.candidate.seg-entities",
        "status": "CANDIDATE",
        "not_catalog": True,
        "mutations": [row],
    }
    intake.content = json.dumps(intake.construction).encode()
    digest = sha256(intake.content).hexdigest()
    intake.metadata["source_sha256"] = digest
    intake.objects[intake.request.evidence.resource_id]["attributes"]["sha256"] = digest
    request = intake.request.model_copy(
        update={"construction_id": "g8.candidate.seg-entities", "company": None, "chart": None}
    )
    plan = candidates.preview(intake.principal, request)
    assert plan["can_submit"] and plan["mutation_count"] == 3
    entity = next(
        item for item in plan["proposal"]["mutations"] if item["object_type"] == "LegalEntity"
    )
    assert entity["evidence_class"] == "USER_ASSERTED"
    assert entity["attributes"] == {"evidence_id": str(request.evidence.resource_id)}
    assert plan["rows"][0]["original"]["attributes"]["parent_key"] == "UNVERIFIED"
    intake.content = b"{}"
    assert not candidates.preview(intake.principal, request)["can_submit"]


def test_permissions_and_request_bounds_precede_native_submission(intake):
    no_propose = intake.principal.model_copy(update={"permissions": ("ontology_read",)})
    with pytest.raises(HTTPException):
        candidates.submit(no_propose, intake.request)
    with pytest.raises(ValidationError):
        CandidateIntakeRequest.model_validate({**intake.request.model_dump(), "limit": 26})
    with pytest.raises(ValidationError):
        CandidateIntakeRequest.model_validate(
            {**intake.request.model_dump(), "valid_from": datetime(2026, 1, 1)}
        )
    assert not intake.submitted

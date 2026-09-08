"""Offline exact source exceptions and immutable retention boundaries."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_company_financial_metrics import metric_case, run  # noqa: F401
from test_semantic_entity_movements import case as workspace_case  # noqa: F401

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.domain.source_reconciliation_exception import SourceExceptionRequest
from finai_api.services import source_reconciliation_exception as service
from finai_api.services.entity_movement_review import digest
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def case(metric_case):
    original, receipt, projection = metric_case
    run(metric_case)
    history, _, _ = service.semantic_analysis.load(None, original.invocation_id)
    pins = {
        str(p.resource_id): p.model_dump(mode="json")
        for p in [projection.descriptor.company, *projection.descriptor.definitions]
    }
    context = [
        pins.get(ref["resource_id"], {**ref, "content_hash": "b" * 64})
        for ref in receipt["selection"].values()
    ]
    request = SourceExceptionRequest(
        company_id=original.company_id,
        invocation_id=original.invocation_id,
        journal_snapshot_at=original.snapshot_at,
        expected_reconciliation_receipt_hash=receipt["receipt_hash"],
        coordinate="Base!S2",
    )
    principal = Principal(
        actor_id="test",
        display_name="Test",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id=str(original.company_id),
            period="2025-01",
            currency="GEL",
        ),
    )
    return principal, request, receipt, projection, history, context


def compile_case(case):
    _, request, receipt, projection, history, context = case
    return service.compile_observation(request, receipt, projection, history, context)


def reseal(case):
    principal, request, receipt, *rest = case
    receipt["receipt_hash"] = digest({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return (
        principal,
        request.model_copy(
            update={"expected_reconciliation_receipt_hash": receipt["receipt_hash"]}
        ),
        receipt,
        *rest,
    )


def test_matched_is_observation_only_with_exact_context(case):
    result = compile_case(case)
    assert result.state == "MATCHED_AT_SNAPSHOT" and not result.finding_eligible
    assert result.matched_journals[0].model_dump(mode="json") == case[2]["accepted"][0]["journal"]
    assert result.source.coordinate == "Base!S2" and result.source.row == 2
    assert result.source.invocation_receipt_hash == case[4]["receipt_hash"]
    assert result.financial_impact is None and result.materiality == "UNASSESSED"
    assert result.automatic_resolution is False and result.business_effect_authorized is False
    assert result == compile_case(case)


def test_unmatched_is_only_eligible_state_and_clocks_stay_separate(case):
    case[2].update(
        status="UNAVAILABLE",
        accepted=[],
        missing_coordinates=["Base!S2"],
        movement_trial_balance=None,
        matched_source_amount=None,
        journal_debit_total=None,
        journal_credit_total=None,
    )
    request = case[1].model_copy(
        update={"journal_snapshot_at": case[1].journal_snapshot_at + timedelta(hours=1)}
    )
    case[2]["snapshot_at"] = request.journal_snapshot_at.isoformat()
    result = compile_case(reseal((case[0], request, *case[2:])))
    assert result.state == "UNMATCHED_AT_SNAPSHOT" and result.finding_eligible
    assert result.journal_observed_at != result.source_known_at
    assert result.financial_impact is None and result.matched_journals == []


def test_s288_missing_literal_stays_excluded_never_candidate(case):
    excluded = {"row": 288, "coordinate": "Base!S288", "reason": "MISSING_LITERAL_POSTED_AMOUNT"}
    case[2]["excluded_rows"] = [excluded]
    review = case[4]["output"]["entity_movement_review"]["reconciliation"]
    review["excluded_rows"] = [excluded]
    case[4]["output"]["source_rows"].append({"row": 288, "cells": {}, "numeric_observations": {}})
    request = case[1].model_copy(update={"coordinate": "Base!S288"})
    result = compile_case(reseal((case[0], request, *case[2:])))
    assert result.state == "EXCLUDED_SOURCE_VALUE" and not result.finding_eligible
    assert result.exclusion_reason == "MISSING_LITERAL_POSTED_AMOUNT"
    assert result.financial_impact is None and result.matched_journals == []


@pytest.mark.parametrize(
    "failure",
    [
        "unknown",
        "supplementary",
        "company",
        "invocation",
        "snapshot",
        "receipt",
        "tamper",
        "context",
        "source_hash",
        "binding",
        "source_clock",
        "row",
    ],
)
def test_wrong_context_or_unverified_source_refused(case, failure):
    principal, request, receipt, projection, history, context = case
    if failure in ("unknown", "supplementary"):
        request = request.model_copy(
            update={"coordinate": "Base!S999" if failure == "unknown" else "Base!AD2"}
        )
    elif failure in ("company", "invocation"):
        request = request.model_copy(update={failure + "_id": uuid4()})
    elif failure == "snapshot":
        request = request.model_copy(
            update={"journal_snapshot_at": request.journal_snapshot_at + timedelta(hours=1)}
        )
    elif failure == "receipt":
        request = request.model_copy(update={"expected_reconciliation_receipt_hash": "0" * 64})
    elif failure == "tamper":
        receipt["status"] = "UNAVAILABLE"
    elif failure == "context":
        context[0]["version_id"] = str(uuid4())
    elif failure == "source_hash":
        history["output"]["source_document"]["sha256"] = "0" * 64
    elif failure == "binding":
        history["output"]["source_document"]["binding"]["version_id"] = str(uuid4())
    elif failure == "source_clock":
        history["output"]["query"]["known_at"] = "2025-01-01T00:00:00Z"
    else:
        history["output"]["source_rows"] = []
    with pytest.raises(WorkspaceError):
        compile_case((principal, request, receipt, projection, history, context))


def test_request_requires_receipt_and_refuses_caller_numbers(case):
    payload = case[1].model_dump(mode="json")
    with pytest.raises(ValidationError):
        SourceExceptionRequest.model_validate({**payload, "amount": "100"})
    del payload["expected_reconciliation_receipt_hash"]
    with pytest.raises(ValidationError):
        SourceExceptionRequest.model_validate(payload)


def test_retained_read_never_reconciles_again(case, monkeypatch):
    principal, request, *_ = case
    observation = compile_case(case)
    monkeypatch.setattr(service, "resolve", lambda p, r: observation)
    store = {}

    def retain(p, result, *, runtime):
        assert p == principal and runtime == service.RUNTIME
        payload = {
            **result,
            "scope": p.scope.model_dump(mode="json"),
            "calculation_runtime": runtime,
            "read_permissions": ["ontology_read"],
        }
        payload["run_id"] = "fcr_" + digest(payload)
        store[payload["run_id"]] = payload
        return payload

    monkeypatch.setattr(service.fact_runs, "retain_run", retain)
    retained = service.retain(principal, request)
    monkeypatch.setattr(service.fact_runs, "read_run", lambda p, r: deepcopy(store[r]))
    monkeypatch.setattr(
        service, "resolve", lambda *a: pytest.fail("Retained read must not resolve again")
    )
    assert service.read(principal, retained["run_id"]) == retained
    store[retained["run_id"]]["calculation_runtime"] = "other/1"
    with pytest.raises(WorkspaceError):
        service.read(principal, retained["run_id"])


def test_resolve_uses_exact_readers_and_foreign_company_refuses_before_read(case, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    principal, request, receipt, projection, history, context = case

    def reconcile(p, invocation, company, snapshot):
        assert (p, invocation, company, snapshot) == (
            principal,
            request.invocation_id,
            request.company_id,
            request.journal_snapshot_at,
        )
        return {"reconciliation": receipt, "source_projection": projection}

    versions = {p["resource_id"]: p for p in context}
    resolver = SimpleNamespace(
        read_session=lambda: nullcontext(), version=lambda ref: versions[ref["resource_id"]]
    )
    monkeypatch.setattr(service.journal_reconciliation, "reconcile", reconcile)
    monkeypatch.setattr(service.semantic_analysis, "load", lambda *a: (history, {}, resolver))
    assert service.resolve(principal, request) == compile_case(case)
    foreign = principal.model_copy(
        update={"scope": principal.scope.model_copy(update={"legal_entity_id": str(uuid4())})}
    )
    with pytest.raises(WorkspaceError, match="selected company"):
        service.resolve(foreign, request)


@pytest.mark.parametrize(
    "failure", ["contract", "company", "scope", "hash", "state", "run", "invalid_id"]
)
def test_immutable_read_refuses_foreign_or_corrupt_evidence(case, monkeypatch, failure):
    principal = case[0]
    payload = {
        **compile_case(case).model_dump(mode="json"),
        "run_id": "fcr_" + "c" * 64,
        "calculation_runtime": service.RUNTIME,
        "scope": principal.scope.model_dump(mode="json"),
        "read_permissions": ["ontology_read"],
    }
    run_id = payload["run_id"]
    if failure == "contract":
        payload["contract"] = "other/1"
    elif failure == "company":
        payload["company"]["resource_id"] = str(uuid4())
    elif failure == "scope":
        payload["scope"]["legal_entity_id"] = str(uuid4())
    elif failure == "hash":
        payload["receipt_hash"] = "0" * 64
    elif failure == "state":
        payload["finding_eligible"] = True
    elif failure == "run":
        payload["run_id"] = "fcr_" + "d" * 64
    else:
        run_id = "not-a-run"
    monkeypatch.setattr(service.fact_runs, "read_run", lambda *a: payload)
    with pytest.raises(WorkspaceError):
        service.read(principal, run_id)

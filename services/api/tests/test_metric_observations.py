"""Offline contract checks; never open the product database or execute a Function."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from finai_api.domain.metric_execution import ObserveRequest
from finai_api.domain.review import Principal
from finai_api.services import metric_execution as metrics
from finai_api.services.workspace import WorkspaceError


def exact(n):
    return dict(
        resource_id=str(UUID(int=n)), version_id=str(UUID(int=n + 100)), content_hash=f"{n:064x}"
    )


@pytest.fixture
def case(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline contract must not access persistence")

    monkeypatch.setattr(metrics.resources, "resource_connection", forbidden)
    monkeypatch.setattr(metrics.fact_runs, "read_run", forbidden)
    monkeypatch.setattr(metrics.fact_runs, "retain_run", forbidden)
    monkeypatch.setattr(metrics.function_invocations, "history", forbidden)
    p = Principal(
        actor_id="offline",
        display_name="Offline",
        permissions=("ontology_read",),
        scope=dict(
            tenant_id=UUID(int=1), legal_entity_id="company", period="2026-09", currency="GEL"
        ),
    )
    when = datetime(2026, 9, 8, tzinfo=UTC)
    fn = {
        **exact(2),
        "object_type": "FunctionDefinition",
        "authority_state": "APPROVED",
        "relation": "FIELD:function_id",
        "attributes": {"definition": {"implementation_id": "ontology.object-set-derived/v1"}},
    }
    metric = {
        **exact(3),
        "object_type": "MetricDefinition",
        "authority_state": "APPROVED",
        "evidence_class": "SOURCE_BOUND",
        "system_from": when,
        "valid_from": when,
        "attributes": {
            "function_id": fn["resource_id"],
            "definition": {
                "contract": "metric-definition/1",
                "selector": {"kind": "OBJECT_COUNT"},
                "unit": {"kind": "COUNT", "symbol": "objects"},
                "grain": "OBJECT_SET_SNAPSHOT",
                "dimensions": [],
                "aggregation": "non_additive",
            },
        },
        "dependencies": [fn],
    }
    req = ObserveRequest(
        metric=exact(3),
        invocation_id=UUID(int=4),
        expected_receipt_hash="a" * 64,
        valid_at=when,
        known_at=when,
    )
    manifest = {"implementation_id": "ontology.object-set-derived/v1"}
    output = {
        "contract": "function-result/1",
        "scope": p.scope.model_dump(mode="json"),
        "calculation_runtime": "shared-functions/1",
        "run_id": "fcr_" + "b" * 64,
        "invocation_request_id": str(req.invocation_id),
        "invocation_plan_hash": "c" * 64,
        "function": exact(2),
        "implementation": manifest,
        "coverage": "COMPLETE_BOUNDED_MATERIALIZATION",
        "total": 1,
        "objects": [exact(5)],
        "query": {"offset": 0, "valid_at": when, "known_at": when},
    }
    receipt = {
        "request": {"request_id": str(req.invocation_id), "valid_at": when, "known_at": when},
        "exact_scope": output["scope"],
        "run_id": output["run_id"],
        "plan_hash": "c" * 64,
        "function": exact(2),
        "implementation": manifest,
    }
    for evidence in (receipt, output):
        evidence.update(current_use_authorized=False, business_effect_authorized=False)
    h = {
        "status": "SUCCEEDED",
        "invocation_id": str(req.invocation_id),
        "receipt_hash": "a" * 64,
        "receipt": receipt,
        "output": output,
    }
    return p, req, metric, h


def test_complete_count_and_zero_preserve_retained_context(case):
    _, _, _, h = case
    result = metrics.assemble(*case)
    assert result["observation"]["value"] == "1"
    assert result["source_result"] == h["output"]
    assert result["function"] == exact(2)
    assert result["current_use_authorized"] is result["business_effect_authorized"] is False
    h["output"].update(total=0, objects=[])
    assert metrics.assemble(*case)["observation"]["value"] == "0"


@pytest.mark.parametrize(
    "change",
    [
        lambda m, h: h.update(status="FAILED"),
        lambda m, h: h.update(receipt_hash="f" * 64),
        lambda m, h: h["output"].update(function=exact(6)),
        lambda m, h: h["output"].update(coverage="QUERY_PAGE_ONLY"),
        lambda m, h: h["output"].update(total=2),
        lambda m, h: h["output"]["query"].update(offset=1),
        lambda m, h: h["output"].update(next_offset=1),
        lambda m, h: h["output"].update(scope={}),
        lambda m, h: h["output"].update(invocation_plan_hash="f" * 64),
        lambda m, h: m["dependencies"][0].update(version_id=str(UUID(int=500))),
        lambda m, h: m.update(evidence_class="REFERENCE_TEMPLATE"),
        lambda m, h: m["attributes"].pop("definition"),
        lambda m, h: h["output"].update(current_use_authorized=True),
        lambda m, h: h["receipt"].update(business_effect_authorized=True),
    ],
)
def test_refuse_partial_wrong_scope_drift_or_legacy(case, change):
    _, _, metric, h = case
    change(metric, h)
    with pytest.raises(WorkspaceError):
        metrics.assemble(*case)


def test_measure_preserves_decimal_currency_company_coverage_and_account_tree(case):
    p, req, metric, h = case
    p = p.model_copy(
        update={"scope": p.scope.model_copy(update={"legal_entity_id": str(UUID(int=8))})}
    )
    h["receipt"]["exact_scope"] = p.scope.model_dump(mode="json")
    h["output"]["scope"] = p.scope.model_dump(mode="json")
    company = {
        **exact(8),
        "relation": "FIELD:legal_entity_id",
        "object_type": "LegalEntity",
        "authority_state": "APPROVED",
    }
    unit = {
        **exact(9),
        "relation": "METRIC_UNIT",
        "object_type": "Currency",
        "authority_state": "APPROVED",
    }
    metric["dependencies"] += [company, unit]
    metric["attributes"]["legal_entity_id"] = company["resource_id"]
    spec = metric["attributes"]["definition"]
    spec.update(
        selector={"kind": "MEASURE", "key": "net_movement"},
        unit={"kind": "CURRENCY", "reference": exact(9)},
        grain="COMPANY_MOVEMENTS",
    )
    value = dict(
        key="net_movement",
        state="VALUE",
        value="-123.4500",
        unit=spec["unit"],
        grain=spec["grain"],
        dimensions=[],
        company=exact(8),
        valid_at=req.valid_at,
        known_at=req.known_at,
        coverage="PARTIAL",
        contributors=[exact(8), exact(9)],
    )
    h["output"].update(
        metric_outputs=[value], financial_metrics={"ledger_completeness": "UNESTABLISHED"}
    )
    result = metrics.assemble(p, req, metric, h)
    assert result["observation"]["value"] == "-123.4500"
    assert result["observation"]["coverage"] == "PARTIAL"
    assert result["source_result"]["financial_metrics"]["ledger_completeness"] == "UNESTABLISHED"
    foreign = p.model_copy(
        update={"scope": p.scope.model_copy(update={"legal_entity_id": str(UUID(int=7))})}
    )
    foreign_history = deepcopy(h)
    foreign_history["receipt"]["exact_scope"] = foreign.scope.model_dump(mode="json")
    foreign_history["output"]["scope"] = foreign.scope.model_dump(mode="json")
    with pytest.raises(WorkspaceError):
        metrics.assemble(foreign, req, metric, foreign_history)
    for key, bad in [
        ("grain", "ACCOUNT"),
        ("company", exact(7)),
        ("dimensions", ["account"]),
        ("unit", {"kind": "COUNT"}),
        ("known_at", "2026-09-09T00:00:00Z"),
    ]:
        changed = deepcopy(h)
        changed["output"]["metric_outputs"][0][key] = bad
        with pytest.raises(WorkspaceError):
            metrics.assemble(p, req, metric, changed)


def test_history_only_reads_immutable_fact_run(case, monkeypatch):
    p, _, _, _ = case
    retained = {
        **metrics.assemble(*case),
        "calculation_runtime": metrics.RUNTIME,
        "run_id": "fcr_saved",
    }
    calls = []

    def read(principal, identity):
        calls.append((principal, identity))
        return retained

    monkeypatch.setattr(metrics.fact_runs, "read_run", read)
    assert metrics.history(p, "fcr_saved") is retained
    assert calls == [(p, "fcr_saved")]


def test_legacy_publication_is_allowed_but_partial_execution_is_rejected(case):
    attrs = {"code": "legacy", "function_reference": "text-only"}
    item = SimpleNamespace(attributes=attrs, resource_id=UUID(int=3))
    metrics.validate_publication(item, None)
    attrs["function_id"] = str(UUID(int=2))
    with pytest.raises(WorkspaceError):
        metrics.validate_publication(item, None)


def test_publication_uses_registry_dependency_resolver(case):
    _, _, metric, _ = case
    item = SimpleNamespace(attributes=metric["attributes"], resource_id=UUID(int=3))
    calls = []

    def target(identity, source, relation):
        calls.append((identity, source, relation))
        return metric["dependencies"][0]

    metrics.validate_publication(item, target)
    assert calls == [(str(UUID(int=2)), str(UUID(int=3)), "METRIC_FUNCTION")]


def test_observe_reuses_history_and_existing_retention(case, monkeypatch):
    p, req, metric, retained = case
    monkeypatch.setattr(metrics, "definition", lambda principal, expected: metric)
    monkeypatch.setattr(
        metrics.function_invocations, "history", lambda principal, identity: retained
    )
    writes = []

    def retain(principal, payload, *, runtime):
        writes.append((principal, payload, runtime))
        return {**payload, "run_id": "fcr_saved", "calculation_runtime": runtime}

    monkeypatch.setattr(metrics.fact_runs, "retain_run", retain)
    result = metrics.observe(p, req)
    assert result["run_id"] == "fcr_saved"
    assert len(writes) == 1
    assert writes[0][0] == p and writes[0][2] == metrics.RUNTIME
    assert writes[0][1]["input_run_id"] == retained["output"]["run_id"]

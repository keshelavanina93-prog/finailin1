"""Offline adapter-to-observation integration; no accepted business records are created."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_accepted_movements_function import accepted_case  # noqa: F401
from test_company_financial_metrics import metric_case  # noqa: F401
from test_semantic_entity_movements import case as workspace_case  # noqa: F401

from finai_api.domain.metric_execution import ObserveRequest
from finai_api.main import app
from finai_api.services import accepted_movements_function as adapter
from finai_api.services import function_execution, metric_execution
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def bridge(accepted_case):
    principal, request, result, company, _ = accepted_case
    function = {**request.function.model_dump(mode="json"), "content_hash": "f" * 64}
    plan = {
        "accepted_movements": adapter.input_plan(principal, request, company),
        "function": function,
        "implementation": function_execution.manifest(
            function_execution.ACCEPTED_MOVEMENTS_IMPLEMENTATION_ID
        ),
        "static_dependencies": [],
        "plan_hash": "a" * 64,
    }
    output = adapter.execute(principal, request, plan)
    output.update(
        scope=principal.scope.model_dump(mode="json"),
        calculation_runtime="shared-functions/1",
        run_id="fcr_" + "b" * 64,
        invocation_request_id=str(request.request_id),
        invocation_plan_hash=plan["plan_hash"],
    )
    receipt = {
        "request": request.model_dump(mode="json"),
        "exact_scope": output["scope"],
        "function": function,
        "implementation": plan["implementation"],
        "plan_hash": plan["plan_hash"],
        "run_id": output["run_id"],
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }
    history = {
        "status": "SUCCEEDED",
        "invocation_id": str(request.request_id),
        "receipt_hash": "c" * 64,
        "receipt": receipt,
        "output": output,
    }
    unit = output["metric_outputs"][0]["unit"]
    definition = {
        "resource_id": str(uuid4()),
        "version_id": str(uuid4()),
        "content_hash": "d" * 64,
        "object_type": "MetricDefinition",
        "authority_state": "APPROVED",
        "evidence_class": "SOURCE_BOUND",
        "system_from": request.known_at,
        "valid_from": request.valid_at,
        "attributes": {
            "code": "test-only-movement",
            "function_reference": function_execution.ACCEPTED_MOVEMENTS_IMPLEMENTATION_ID,
            "function_id": function["resource_id"],
            "legal_entity_id": company["resource_id"],
            "definition": {
                "contract": "metric-definition/1",
                "selector": {"kind": "MEASURE", "key": "net_movement"},
                "unit": unit,
                "grain": "COMPANY_MOVEMENTS",
                "dimensions": [],
                "aggregation": "non_additive",
            },
        },
        "dependencies": [
            {
                **function,
                "object_type": "FunctionDefinition",
                "authority_state": "APPROVED",
                "relation": "FIELD:function_id",
            },
            {
                **company,
                "object_type": "LegalEntity",
                "authority_state": "APPROVED",
                "relation": "FIELD:legal_entity_id",
            },
            {
                **unit["reference"],
                "object_type": "Currency",
                "authority_state": "APPROVED",
                "relation": "METRIC_UNIT",
            },
        ],
    }
    observation = ObserveRequest(
        metric={key: definition[key] for key in ("resource_id", "version_id", "content_hash")},
        invocation_id=request.request_id,
        expected_receipt_hash=history["receipt_hash"],
        valid_at=request.valid_at,
        known_at=request.known_at,
    )
    return principal, observation, definition, history, result


def test_real_adapter_values_become_exact_observations_without_aggregation(bridge):
    principal, request, definition, history, result = bridge
    for key, expected in result.nodes[0].metrics.items():
        definition["attributes"]["definition"]["selector"]["key"] = key
        observed = metric_execution.assemble(principal, request, definition, history)
        assert observed["observation"]["value"] == expected.value
        assert observed["observation"]["state"] == "VALUE"
        assert result.coverage.state == "RECONCILED"
        assert observed["observation"]["coverage"] == "COMPLETE"
        assert (
            observed["source_result"]["financial_metrics"]["coverage"]["ledger_completeness"]
            == "UNESTABLISHED"
        )
        assert observed["source_result"]["financial_metrics"] == result.model_dump(mode="json")
        assert observed["source_result"]["journal_observed_at"] == result.snapshot_at.isoformat()
        assert observed["current_use_authorized"] is observed["business_effect_authorized"] is False
    changed = deepcopy(history)
    changed["output"]["metric_outputs"][0]["known_at"] = (
        request.known_at + timedelta(microseconds=1)
    ).isoformat()
    definition["attributes"]["definition"]["selector"]["key"] = changed["output"]["metric_outputs"][
        0
    ]["key"]
    with pytest.raises(WorkspaceError):
        metric_execution.assemble(principal, request, definition, changed)


def test_mounted_routes_deny_anonymous_and_insufficient_permission_without_storage(
    bridge, monkeypatch
):
    _, request, _, _, _ = bridge

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Denied requests must not reach storage")

    monkeypatch.setattr(metric_execution, "definition", forbidden)
    monkeypatch.setattr(metric_execution.fact_runs, "read_run", forbidden)
    client = TestClient(app)
    path = "/v1/ontology/metrics/observations"
    assert client.post(path, json=request.model_dump(mode="json")).status_code == 401
    assert client.get(path + "/fcr_" + "a" * 64).status_code == 401
    assert (
        client.post(
            path,
            json=request.model_dump(mode="json"),
            headers={"Authorization": "Bearer test-token"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            path + "/fcr_" + "a" * 64, headers={"Authorization": "Bearer test-token"}
        ).status_code
        == 403
    )

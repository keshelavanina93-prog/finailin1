# ruff: noqa: F811
"""App-role writes cannot invent retained calculated-value provenance."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, retained  # noqa: F401
from test_retained_calculated_properties import retained_calculation_case

from finai_api.domain.authority import canonical_sha256
from finai_api.services import fact_runs, function_execution, function_invocations


def insert_intent(reader, request, plan):
    with function_invocations._database(reader) as cursor:
        cursor.execute(
            "INSERT INTO function_invocations "
            "(tenant_id,request_id,exact_scope,actor_id,request_hash,request,plan,plan_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                reader.scope.tenant_id,
                request.request_id,
                Jsonb(reader.scope.model_dump(mode="json")),
                reader.actor_id,
                canonical_sha256(request),
                Jsonb(request.model_dump(mode="json")),
                Jsonb(plan),
                plan["plan_hash"],
            ),
        )


@DB
def test_native_database_rejects_forged_calculated_pins_and_values(retained, monkeypatch):
    case = retained_calculation_case(retained, monkeypatch)
    reader, request = case["reader"], case["request"]
    plan = function_execution.plan(reader, request)
    forged_plan = deepcopy(plan)
    forged_plan["retained_properties"][0]["schema"] = {
        **forged_plan["retained_properties"][0]["schema"],
        "version_id": str(uuid4()),
    }
    forged_plan["plan_hash"] = function_execution._digest(
        {key: value for key, value in forged_plan.items() if key != "plan_hash"}
    )
    with pytest.raises(psycopg.errors.RaiseException, match="reviewed pins"):
        insert_intent(reader, request, forged_plan)
    insert_intent(reader, request, plan)
    output = function_execution.execute_plan(reader, plan)
    for failure in ("changed_value", "missing_value"):
        forged_output = deepcopy(output)
        if failure == "changed_value":
            forged_output["consumed_property_values"][0]["value"] = "SYNTHETIC invented value"
        else:
            forged_output["consumed_property_values"] = []
        retained_output = fact_runs.retain_run(
            reader,
            {
                **forged_output,
                "invocation_request_id": str(request.request_id),
                "invocation_plan_hash": plan["plan_hash"],
            },
            runtime="shared-functions/1",
        )
        now = datetime.now(UTC).isoformat()
        payload = {
            "request": request.model_dump(mode="json"),
            "exact_scope": reader.scope.model_dump(mode="json"),
            "function": plan["function"],
            "implementation": plan["implementation"],
            "request_id": str(request.request_id),
            "plan_hash": plan["plan_hash"],
            "status": "SUCCEEDED",
            "started_at": now,
            "completed_at": now,
            "mode": "EVIDENCE_ANALYSIS_ONLY",
            "current_use_authorized": False,
            "business_effect_authorized": False,
            "run_id": retained_output["run_id"],
        }
        with (
            pytest.raises(psycopg.errors.RaiseException, match="exact upstream receipt"),
            function_invocations._database(reader) as cursor,
        ):
            cursor.execute(
                "INSERT INTO function_invocation_results "
                "(tenant_id,request_id,exact_scope,actor_id,status,run_id,payload,proof_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    reader.scope.tenant_id,
                    request.request_id,
                    Jsonb(reader.scope.model_dump(mode="json")),
                    reader.actor_id,
                    payload["status"],
                    retained_output["run_id"],
                    Jsonb(payload),
                    function_invocations._digest(payload),
                ),
            )
    # Rejected writes leave the valid intent resumable through the canonical runner.
    result = function_invocations.invoke(reader, request)
    assert result["status"] == "SUCCEEDED", result
    assert result["output"]["consumed_property_values"] == output["consumed_property_values"]

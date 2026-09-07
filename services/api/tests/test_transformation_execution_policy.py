# ruff: noqa: F811
"""Concurrency requires an explicit bounded reviewed definition contract."""

from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.transformation import TransformationDefinition, TransformationRunRequest
from finai_api.services import function_execution
from finai_api.services import report_workflows as records
from finai_api.services import transformation_runs as runs


def test_execution_policy_is_explicit_strict_and_bounded():
    original = {
        "definition": {
            "nodes": [{"node_id": "source", "function_id": str(uuid4())}],
            "outputs": [{"output_id": "evidence", "node_id": "source"}],
        },
        "resource_budget": {
            "max_returned_rows": 100,
            "max_derived_evaluations": 100,
            "max_published_result_bytes": 1000000,
        },
    }
    legacy = TransformationDefinition.model_validate(original).model_dump(mode="json")
    assert "execution_policy" not in legacy
    for maximum in (1, 2, 4):
        configured = {**legacy, "execution_policy": {"max_concurrent_nodes": maximum}}
        assert (
            TransformationDefinition.model_validate(configured).model_dump(mode="json")
            == configured
        )
    for maximum in (0, 5, True, "2", 2.0):
        with pytest.raises(ValidationError):
            TransformationDefinition.model_validate(
                {**legacy, "execution_policy": {"max_concurrent_nodes": maximum}}
            )
    with pytest.raises(ValidationError):
        TransformationDefinition.model_validate(
            {**legacy, "execution_policy": {"max_concurrent_nodes": 2, "unbounded": True}}
        )


@DB
def test_sql_rejects_unreviewed_or_changed_execution_policy(retained):
    reader, invocation, _, _, _ = function_case(retained)
    _, publish = retained
    definition = item(
        "TransformationDefinition",
        {
            "execution_policy": {"max_concurrent_nodes": 2},
            "resource_budget": {
                "max_returned_rows": 1,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 1000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source",
                        "function_id": str(invocation.function.resource_id),
                        "limit": 1,
                    }
                ],
                "outputs": [{"output_id": "evidence", "node_id": "source"}],
            },
        },
    )
    for declared in (True, False):
        attributes = dict(definition.attributes)
        if not declared:
            attributes.pop("execution_policy")
        row = publish(item("TransformationDefinition", attributes))[0]
        request = TransformationRunRequest(
            transformation=VersionReference(
                resource_id=row["resource_id"], version_id=row["version_id"]
            ),
            valid_at=invocation.valid_at,
            known_at=invocation.known_at,
        )
        identity = runs.retain(reader, request)
        payload = runs.read(reader, identity)["request"]
        assert ("execution_policy" in payload["compiled_plan"]) is declared
        changes = (
            ({"max_concurrent_nodes": 4}, None) if declared else ({"max_concurrent_nodes": 2},)
        )
        for policy in changes:
            compiled = dict(payload["compiled_plan"])
            if policy is None:
                compiled.pop("execution_policy")
            else:
                compiled["execution_policy"] = policy
            compiled["plan_hash"] = function_execution._digest(
                {key: value for key, value in compiled.items() if key != "plan_hash"}
            )
            with (
                pytest.raises(
                    psycopg.errors.RaiseException,
                    match=r"[Ee]xecution.*[Pp]olicy|[Cc]oncurrent execution",
                ),
                runs.resource_connection(reader) as conn,
            ):
                scope = records.set_scope(conn, reader)
                conn.execute(
                    "INSERT INTO workflow_requests(tenant_id,workflow_id,exact_scope,actor_id,"
                    "definition_version,payload) VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        reader.scope.tenant_id,
                        identity,
                        Jsonb(scope),
                        reader.actor_id,
                        runs.VERSION,
                        Jsonb({**payload, "compiled_plan": compiled}),
                    ),
                )

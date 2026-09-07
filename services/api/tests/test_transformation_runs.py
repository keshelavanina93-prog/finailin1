# ruff: noqa: F811
"""Real native node invocation, reuse and SQL barrier/output refusal."""

from datetime import datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, item, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import report_workflows as records
from finai_api.services import transformation_history
from finai_api.services import transformation_runs as runs
from finai_api.services.workspace import WorkspaceError


@DB
def test_native_two_node_publication_replay_and_forged_topology(retained, monkeypatch):
    reader, invocation, _, _, _ = function_case(retained)
    reader = reader.model_copy(update={"permissions": (*reader.permissions, "read", "ingest")})
    _, publish = retained
    definition = item(
        "TransformationDefinition",
        {
            "resource_budget": {
                "max_returned_rows": 100,
                "max_derived_evaluations": 800,
                "max_published_result_bytes": 16000000,
            },
            "definition": {
                "nodes": [
                    {"node_id": "first", "function_id": str(invocation.function.resource_id)},
                    {
                        "node_id": "second",
                        "function_id": str(invocation.function.resource_id),
                        "depends_on": ["first"],
                    },
                ],
                "outputs": [{"output_id": "observations", "node_id": "second"}],
            },
        },
    )
    row = publish(definition)[0]
    request = TransformationRunRequest(
        transformation=VersionReference(
            resource_id=row["resource_id"], version_id=row["version_id"]
        ),
        valid_at=invocation.valid_at,
        known_at=invocation.known_at,
    )
    identity = runs.retain(reader, request)
    assert runs.retain(reader, request) == identity
    context = {
        "workflow_id": identity,
        "actor_id": reader.actor_id,
        "scope": reader.scope.model_dump(mode="json"),
    }
    monkeypatch.setattr(records, "current_principal", lambda *_: reader)
    with pytest.raises(WorkspaceError, match="barrier"):
        runs.execute_node({**context, "node_id": "second"})
    with pytest.raises(psycopg.errors.RaiseException):
        records.event(
            reader,
            identity,
            "node:first:terminal",
            {
                "node": "first",
                "state": "COMPLETED",
                "output": {},
                "new_run_required": False,
            },
        )
    first = runs.execute_node({**context, "node_id": "first"})
    assert runs.execute_node({**context, "node_id": "first"}) == first
    assert first["usage"]["returned_rows"] == 1
    assert first["usage"]["measurement"] == "POSTGRES_JSONB_TEXT_UTF8_V1"
    with pytest.raises(psycopg.errors.RaiseException):
        records.event(
            reader,
            identity,
            "node:first:terminal",
            {**first, "usage": {**first["usage"], "published_result_bytes": 0}},
        )
    with pytest.raises(WorkspaceError, match="incomplete"):
        runs.publish(context)
    runs.execute_node({**context, "node_id": "second"})
    publication = runs.publish(context)
    assert runs.publish(context) == publication
    result = runs.read(reader, identity)
    assert len(result["publications"]) == 1
    assert runs.cumulative_usage(result["events"])["returned_rows"] == 2
    with records.scope_connection(reader) as conn:
        records.set_scope(conn, reader)
        retained_row = conn.execute(
            "SELECT payload FROM workflow_requests WHERE tenant_id=%s AND workflow_id=%s",
            (reader.scope.tenant_id, identity),
        ).fetchone()[0]
    bad = {
        **retained_row,
        "compiled_plan": {**retained_row["compiled_plan"], "node_order": ["second", "first"]},
    }
    with (
        pytest.raises(psycopg.errors.RaiseException, match="dependency order"),
        runs.resource_connection(reader) as conn,
    ):
        records.set_scope(conn, reader)
        conn.execute(
            "INSERT INTO workflow_requests "
            "(tenant_id,workflow_id,exact_scope,actor_id,definition_version,payload) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                reader.scope.tenant_id,
                identity,
                Jsonb(context["scope"]),
                reader.actor_id,
                runs.VERSION,
                Jsonb(bad),
            ),
        )
    failed_identity = runs.retain(reader, request.model_copy(update={"request_id": uuid4()}))
    failed_context = {**context, "workflow_id": failed_identity}

    def fail(*_):
        raise RuntimeError("Synthetic Function adapter failure")

    with monkeypatch.context() as patch:
        patch.setattr(runs.function_execution, "execute_plan", fail)
        outcome = runs.execute_node({**failed_context, "node_id": "first"})
    assert outcome["state"] == "FAILED" and outcome["new_run_required"]
    with pytest.raises(WorkspaceError, match="incomplete"):
        runs.publish(failed_context)
    assert runs.read(reader, failed_identity)["publications"] == []
    with monkeypatch.context() as patch:
        patch.setattr(runs.function_execution, "plan", lambda *_: pytest.fail("History replanned"))
        first_page = transformation_history.discover(reader, limit=1)
        cursor = first_page["next_cursor"]
        assert first_page["items"][0]["workflow_id"] == failed_identity
        assert first_page["items"][0]["failed_steps"] == 1
        second_page = transformation_history.discover(
            reader, 1, datetime.fromisoformat(cursor["created_at"]), UUID(cursor["request_id"])
        )
        assert second_page["next_cursor"] is None
        historical = second_page["items"][0]
        assert historical["workflow_id"] == identity
        assert historical["completed_steps"] == historical["total_steps"] == 2
        assert historical["published_output_sets"] == 1
        assert "runtime_status" not in historical
        stranger = reader.model_copy(
            update={"scope": reader.scope.model_copy(update={"legal_entity_id": "other-company"})}
        )
        assert transformation_history.discover(stranger)["items"] == []
    with pytest.raises(WorkspaceError, match="both cursor"):
        transformation_history.discover(reader, before_request_id=uuid4())


@DB
def test_actual_result_byte_budget_refuses_publication_and_replay_does_not_charge_twice(
    retained, monkeypatch
):
    reader, invocation, _, _, _ = function_case(retained)
    reader = reader.model_copy(update={"permissions": (*reader.permissions, "read", "ingest")})
    _, publish = retained
    definition = item(
        "TransformationDefinition",
        {
            "resource_budget": {
                "max_returned_rows": 1,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 1,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "limited",
                        "function_id": str(invocation.function.resource_id),
                        "limit": 1,
                    }
                ],
                "outputs": [{"output_id": "result", "node_id": "limited"}],
            },
        },
    )
    row = publish(definition)[0]
    request = TransformationRunRequest(
        transformation=VersionReference(
            resource_id=row["resource_id"], version_id=row["version_id"]
        ),
        valid_at=invocation.valid_at,
        known_at=invocation.known_at,
    )
    identity = runs.retain(reader, request)
    context = {
        "workflow_id": identity,
        "actor_id": reader.actor_id,
        "scope": reader.scope.model_dump(mode="json"),
        "node_id": "limited",
    }
    monkeypatch.setattr(records, "current_principal", lambda *_: reader)
    refusal = runs.execute_node(context)
    assert refusal["state"] == "BUDGET_REFUSED"
    assert refusal["usage"]["published_result_bytes"] > 1
    assert refusal["usage"]["returned_rows"] == 1
    assert refusal["cumulative_usage"] == refusal["usage"]
    assert runs.execute_node(context) == refusal
    result = runs.read(reader, identity)
    assert len([event for event in result["events"] if event["state"] == "BUDGET_REFUSED"]) == 1
    assert not any(
        event["state"] in ("COMPLETED", "STAGED", "PUBLISHED") for event in result["events"]
    )
    with pytest.raises(WorkspaceError, match="incomplete"):
        runs.publish(context)
    assert result["publications"] == []

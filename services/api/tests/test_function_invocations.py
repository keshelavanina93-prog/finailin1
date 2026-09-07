# ruff: noqa: F811
"""Native invocation persistence over a real synthetic canonical Function adapter."""

from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.services import function_execution, function_invocations
from finai_api.services.workspace import WorkspaceError


@DB
def test_real_invocation_replay_history_scope_and_sql_forgery(retained, monkeypatch):
    reader, request, _, _, _ = function_case(retained)
    first = function_invocations.invoke(reader, request)
    assert first["status"] == "SUCCEEDED"
    assert first["output"]["run_id"].startswith("fcr_")
    assert len(first["output"]["objects"]) == 1
    assert first["current_use_authorized"] is False
    with monkeypatch.context() as patch:
        patch.setattr(
            function_execution, "execute_plan", lambda *_: pytest.fail("Repeated execution")
        )
        patch.setattr(function_execution, "plan", lambda *_: pytest.fail("Repeated planning"))
        assert function_invocations.invoke(reader, request) == first
        reopened = function_invocations.history(reader, request.request_id)
        assert reopened["receipt_hash"] == first["receipt_hash"]
    with pytest.raises(WorkspaceError, match="another request"):
        function_invocations.invoke(reader, request.model_copy(update={"limit": 1}))
    stranger = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(update={"legal_entity_id": "unrelated-" + uuid4().hex})
        }
    )
    with pytest.raises(WorkspaceError) as hidden:
        function_invocations.history(stranger, request.request_id)
    assert hidden.value.status == 404
    with function_invocations._database(reader) as cursor:
        intent = cursor.execute(
            "SELECT * FROM function_invocations WHERE tenant_id=%s AND request_id=%s",
            (reader.scope.tenant_id, request.request_id),
        ).fetchone()
    forged_id = uuid4()
    forged_request = {**intent["request"], "request_id": str(forged_id)}
    forged_plan = {**intent["plan"], "request": forged_request, "static_dependencies": []}
    with (
        pytest.raises(psycopg.errors.RaiseException),
        function_invocations._database(reader) as cursor,
    ):
        cursor.execute(
            "INSERT INTO function_invocations "
            "(tenant_id,request_id,exact_scope,actor_id,request_hash,request,plan,plan_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                reader.scope.tenant_id,
                forged_id,
                Jsonb(intent["exact_scope"]),
                reader.actor_id,
                intent["request_hash"],
                Jsonb(forged_request),
                Jsonb(forged_plan),
                intent["plan_hash"],
            ),
        )


@DB
def test_interruption_reuses_committed_intent_and_failure_is_terminal(retained, monkeypatch):
    reader, request, _, _, _ = function_case(retained)
    original = function_execution.execute_plan

    def interrupted(*_):
        raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(function_execution, "execute_plan", interrupted)
        with pytest.raises(KeyboardInterrupt):
            function_invocations.invoke(reader, request)
    interrupted_history = function_invocations.history(reader, request.request_id)
    assert interrupted_history["status"] == "INTENT_RETAINED"
    assert interrupted_history["receipt"]["request"] == request.model_dump(mode="json")
    with monkeypatch.context() as patch:
        patch.setattr(function_execution, "execute_plan", original)
        assert function_invocations.invoke(reader, request)["status"] == "SUCCEEDED"
    failed_request = request.model_copy(update={"request_id": uuid4()})

    def failed(*_):
        raise RuntimeError("SECRET source content must never enter a receipt")

    with monkeypatch.context() as patch:
        patch.setattr(function_execution, "execute_plan", failed)
        result = function_invocations.invoke(reader, failed_request)
    assert result["status"] == "FAILED" and result["output"] is None
    assert result["receipt"]["failure_code"] == "EXECUTION_FAILED"
    assert "SECRET" not in str(result)
    assert function_invocations.invoke(reader, failed_request) == result

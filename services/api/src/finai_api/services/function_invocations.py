"""Persistent bounded invocation evidence over existing content-addressed fact runs."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import fact_runs
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@contextmanager
def _database(principal: Principal):
    with resource_connection(principal) as conn:
        conn.execute(
            "SELECT set_config('finai.exact_scope',%s,true)",
            (json.dumps(principal.scope.model_dump(mode="json")),),
        )
        with conn.cursor(row_factory=dict_row) as cursor:
            yield cursor


def _terminal(principal: Principal, request_id: UUID) -> dict | None:
    with _database(principal) as cursor:
        row = cursor.execute(
            "SELECT payload,proof_hash,recorded_at FROM function_invocation_results "
            "WHERE tenant_id=%s AND request_id=%s",
            (principal.scope.tenant_id, request_id),
        ).fetchone()
    if row is None:
        return None
    if _digest(row["payload"]) != row["proof_hash"]:
        raise WorkspaceError(409, "Invocation evidence integrity verification failed")
    result = {
        **row["payload"],
        "proof_hash": row["proof_hash"],
        "recorded_at": row["recorded_at"].isoformat(),
    }
    if result["status"] == "SUCCEEDED":
        result["output"] = fact_runs.read_run(principal, result["run_id"])
    return {
        "invocation_id": str(request_id),
        "purpose": "HISTORICAL_INVOCATION_EVIDENCE",
        "status": result["status"],
        "receipt_hash": result["proof_hash"],
        "receipt": {key: value for key, value in result.items() if key != "output"},
        "output": result.get("output"),
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def history(principal: Principal, request_id: UUID) -> dict:
    require_permission(principal, "ontology_read")
    result = _terminal(principal, request_id)
    if result is not None:
        return {**result, "purpose": "HISTORICAL_INVOCATION_EVIDENCE"}
    with _database(principal) as cursor:
        row = cursor.execute(
            "SELECT request_id,request,plan_hash,plan FROM function_invocations "
            "WHERE tenant_id=%s AND request_id=%s",
            (principal.scope.tenant_id, request_id),
        ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Function invocation unavailable in this exact scope")
    return {
        "invocation_id": str(request_id),
        "status": "INTENT_RETAINED",
        "receipt_hash": None,
        "receipt": {
            "request_id": str(request_id),
            "request": row["request"],
            "plan_hash": row["plan_hash"],
            "function": row["plan"]["function"],
        },
        "output": None,
        "purpose": "HISTORICAL_INVOCATION_EVIDENCE",
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def invoke(principal: Principal, request: FunctionInvocation) -> dict:
    from finai_api.services.function_execution import execute_plan, plan

    require_permission(principal, "ontology_read")
    scope = principal.scope.model_dump(mode="json")
    request_hash = canonical_sha256(request)
    # Session lock bridges the committed intent and terminal record, without holding
    # any canonical lock across adapter calls on their own connections.
    with connection(principal.scope) as lock_conn:
        lock_row = lock_conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
            (f"function-invocation:{principal.scope.tenant_id}:{request.request_id}",),
        ).fetchone()
        assert lock_row is not None
        if not lock_row[0]:
            raise WorkspaceError(409, "This function invocation is already executing")
        lock_conn.commit()
        with _database(principal) as cursor:
            intent = cursor.execute(
                "SELECT * FROM function_invocations WHERE tenant_id=%s AND request_id=%s",
                (principal.scope.tenant_id, request.request_id),
            ).fetchone()
        if intent is not None:
            if intent["request_hash"] != request_hash or intent["actor_id"] != principal.actor_id:
                raise WorkspaceError(409, "Invocation identity already used by another request")
            frozen = intent["plan"]
        else:
            frozen = jsonable_encoder(plan(principal, request))
            with _database(principal) as cursor:
                cursor.execute(
                    "INSERT INTO function_invocations "
                    "(tenant_id,request_id,exact_scope,actor_id,request_hash,"
                    "request,plan,plan_hash) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        principal.scope.tenant_id,
                        request.request_id,
                        Jsonb(scope),
                        principal.actor_id,
                        request_hash,
                        Jsonb(request.model_dump(mode="json")),
                        Jsonb(frozen),
                        frozen["plan_hash"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise WorkspaceError(409, "Invocation identity is already retained")
        previous = _terminal(principal, request.request_id)
        if previous is not None:
            return previous
        started = datetime.now(UTC).isoformat()
        run_id = None
        failure = None
        try:
            output = execute_plan(principal, frozen)
            retained = fact_runs.retain_run(
                principal,
                {
                    **output,
                    "invocation_request_id": str(request.request_id),
                    "invocation_plan_hash": frozen["plan_hash"],
                    "current_use_authorized": False,
                    "business_effect_authorized": False,
                },
                runtime="shared-functions/1",
            )
            run_id = retained["run_id"]
        except WorkspaceError:
            failure = "EXECUTION_REJECTED"
        except Exception:
            # Do not persist exception messages containing source text or connection secrets.
            failure = "EXECUTION_FAILED"
        payload = {
            "request": request.model_dump(mode="json"),
            "exact_scope": scope,
            "function": frozen["function"],
            "implementation": frozen["implementation"],
            "request_id": str(request.request_id),
            "plan_hash": frozen["plan_hash"],
            "status": "FAILED" if failure else "SUCCEEDED",
            "started_at": started,
            "completed_at": datetime.now(UTC).isoformat(),
            "mode": "EVIDENCE_ANALYSIS_ONLY",
            "current_use_authorized": False,
            "business_effect_authorized": False,
            **({"failure_code": failure} if failure else {"run_id": run_id}),
        }
        with _database(principal) as cursor:
            cursor.execute(
                "INSERT INTO function_invocation_results "
                "(tenant_id,request_id,exact_scope,actor_id,status,run_id,payload,proof_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    principal.scope.tenant_id,
                    request.request_id,
                    Jsonb(scope),
                    principal.actor_id,
                    payload["status"],
                    run_id,
                    Jsonb(payload),
                    _digest(payload),
                ),
            )
        result = _terminal(principal, request.request_id)
        assert result is not None
        return result

"""Append-only exact-scope production receipts, including every rejected source row."""

import json

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.security import require_permission
from finai_api.services.entity_movement_review import digest
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def verify(row, principal, request=None):
    payload = row["payload"]
    if (
        payload.get("receipt_hash") != row["receipt_hash"]
        or digest({k: v for k, v in payload.items() if k != "receipt_hash"}) != row["receipt_hash"]
    ):
        raise WorkspaceError(
            409, "Retained journal production receipt failed integrity verification"
        )
    if request is not None and (
        row["actor_id"] != principal.actor_id
        or row["request_hash"] != digest(request.model_dump(mode="json"))
    ):
        raise WorkspaceError(
            409, "Journal production request ID was reused for different intent or maker"
        )
    return payload


def history(principal, request_id, phase="SUBMITTED", request=None):
    require_permission(principal, "ontology_read")
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute(
            "SELECT set_config('finai.exact_scope',%s,true)",
            (json.dumps(principal.scope.model_dump(mode="json")),),
        )
        row = cursor.execute(
            "SELECT * FROM journal_production_attempts WHERE tenant_id=%s "
            "AND request_id=%s AND phase=%s",
            (principal.scope.tenant_id, request_id, phase),
        ).fetchone()
    return verify(row, principal, request) if row else None


def retain(principal, request, phase, manifest):
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute(
            "SELECT set_config('finai.exact_scope',%s,true)",
            (json.dumps(principal.scope.model_dump(mode="json")),),
        )
        cursor.execute(
            "INSERT INTO journal_production_attempts "
            "(tenant_id,request_id,phase,exact_scope,actor_id,request_hash,receipt_hash,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                principal.scope.tenant_id,
                request.request_id,
                phase,
                Jsonb(principal.scope.model_dump(mode="json")),
                principal.actor_id,
                digest(request.model_dump(mode="json")),
                manifest["receipt_hash"],
                Jsonb(manifest),
            ),
        )
    return history(principal, request.request_id, phase, request)

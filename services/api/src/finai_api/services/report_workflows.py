"""G8 workflow records. Temporal receives opaque IDs and scope, never source payloads/keys."""

import json
from hashlib import sha256
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services.report_inputs import ReportInputRequest
from finai_api.services.workspace import WorkspaceError, detail
from finai_api.storage import connection

VERSION = "report-source-process/3"
DEFINITION = {
    "version": VERSION,
    "nodes": [
        {"id": "hierarchy", "function": "1c-account-frontier/1", "depends_on": []},
        {"id": "coverage", "function": "mr-source-coverage/1", "depends_on": ["hierarchy"]},
        {"id": "review", "function": "human-review/1", "depends_on": ["coverage"]},
    ],
    "outputs": {"hierarchy": "source-hierarchy/1", "coverage": "source-assessment/1"},
}


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: ReportInputRequest


def scope_connection(principal: Principal) -> Any:
    return connection(principal.scope)


def set_scope(conn: Any, principal: Principal) -> dict[str, Any]:
    scope = principal.scope.model_dump(mode="json")
    conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
    return scope


def retain(principal: Principal, request: WorkflowRequest) -> str:
    for receipt_id in set(request.report.receipt_ids):
        detail(principal, receipt_id)
    payload = request.model_dump(mode="json")
    payload["definition"] = DEFINITION
    identity = (
        "wfr_"
        + sha256(
            json.dumps(
                {
                    "scope": principal.scope.model_dump(mode="json"),
                    "actor": principal.actor_id,
                    "definition": DEFINITION,
                    "request": payload,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
    )
    with scope_connection(principal) as conn:
        scope = set_scope(conn, principal)
        conn.execute(
            "INSERT INTO workflow_requests "
            "(tenant_id,workflow_id,exact_scope,actor_id,definition_version,payload) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                principal.scope.tenant_id,
                identity,
                Jsonb(scope),
                principal.actor_id,
                VERSION,
                Jsonb(payload),
            ),
        )
    return identity


def read(principal: Principal, identity: str) -> dict[str, Any]:
    with scope_connection(principal) as conn:
        scope = set_scope(conn, principal)
        row = conn.execute(
            "SELECT payload,actor_id,created_at FROM workflow_requests "
            "WHERE tenant_id=%s AND exact_scope=%s AND workflow_id=%s",
            (principal.scope.tenant_id, Jsonb(scope), identity),
        ).fetchone()
        if not row:
            raise WorkspaceError(404, "Workflow unavailable in authorized scope")
        events = conn.execute(
            "SELECT event_id,payload,created_at FROM workflow_events "
            "WHERE tenant_id=%s AND exact_scope=%s AND workflow_id=%s "
            "ORDER BY created_at,event_id",
            (principal.scope.tenant_id, Jsonb(scope), identity),
        ).fetchall()
        return {
            "workflow_id": identity,
            "request": row[0],
            "actor_id": row[1],
            "created_at": row[2].isoformat(),
            "definition": row[0].get(
                "definition",
                {
                    "version": "report-source-process/1",
                    "nodes": [
                        {"id": "coverage", "function": "mr-source-coverage/1", "depends_on": []},
                        {"id": "review", "function": "human-review/1", "depends_on": ["coverage"]},
                    ],
                },
            ),
            "events": [{"event_id": e[0], **e[1], "created_at": e[2].isoformat()} for e in events],
        }


def event(principal: Principal, identity: str, event_id: str, payload: dict[str, Any]) -> None:
    with scope_connection(principal) as conn:
        scope = set_scope(conn, principal)
        conn.execute(
            "INSERT INTO workflow_events "
            "(tenant_id,workflow_id,exact_scope,event_id,payload) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (principal.scope.tenant_id, identity, Jsonb(scope), event_id, Jsonb(payload)),
        )
        existing = conn.execute(
            "SELECT payload FROM workflow_events WHERE tenant_id=%s AND workflow_id=%s "
            "AND exact_scope=%s AND event_id=%s",
            (principal.scope.tenant_id, identity, Jsonb(scope), event_id),
        ).fetchone()
        if not existing or existing[0] != payload:
            raise WorkspaceError(409, "Workflow event identity conflicts with retained content")


def current_principal(actor_id: str, scope: dict[str, Any]) -> Principal:
    # Revalidate the current server-owned grant on every activity; no stale permission snapshot.
    from fastapi.security import HTTPAuthorizationCredentials

    from finai_api.config import get_settings

    for token in json.loads(get_settings().access_tokens.get_secret_value()):
        principal = authenticated_principal(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )
        if principal.actor_id == actor_id and principal.scope.model_dump(mode="json") == scope:
            return principal
    raise WorkspaceError(403, "Workflow owner no longer has access")

"""Authorized controls for durable report-source workflows; review is not certification."""

import asyncio
from contextlib import suppress
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from finai_api.config import get_settings
from finai_api.domain.review import Principal
from finai_api.report_workflow import ReportSourceWorkflow
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import report_workflows as records
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/workspace/workflows", tags=["durable workflows"])
User = Annotated[Principal, Depends(authenticated_principal)]


async def client() -> Client:
    settings = get_settings()
    try:
        return await asyncio.wait_for(
            Client.connect(settings.temporal_address, namespace=settings.temporal_namespace),
            timeout=5,
        )
    except Exception as exc:
        raise WorkspaceError(
            503, "Workflow runtime unavailable; retained requests can be retried"
        ) from exc


@router.post("")
async def start(request: records.WorkflowRequest, principal: User) -> dict[str, Any]:
    require_permission(principal, "ingest")
    require_permission(principal, "read")
    identity = await asyncio.to_thread(records.retain, principal, request)
    runtime = await client()
    with suppress(WorkflowAlreadyStartedError):
        await runtime.start_workflow(
            ReportSourceWorkflow.run,
            {
                "workflow_id": identity,
                "definition_version": records.VERSION,
                "actor_id": principal.actor_id,
                "scope": principal.scope.model_dump(mode="json"),
            },
            id=identity,
            task_queue="g8-report-source-v1",
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    return {"workflow_id": identity}


@router.get("")
def listing(principal: User) -> list[dict[str, Any]]:
    require_permission(principal, "read")
    with records.scope_connection(principal) as conn:
        from psycopg.types.json import Jsonb

        scope = records.set_scope(conn, principal)
        rows = conn.execute(
            "SELECT workflow_id,created_at FROM workflow_requests "
            "WHERE tenant_id=%s AND exact_scope=%s ORDER BY created_at DESC LIMIT 50",
            (principal.scope.tenant_id, Jsonb(scope)),
        ).fetchall()
        return [{"workflow_id": row[0], "created_at": row[1].isoformat()} for row in rows]


@router.get("/{identity}")
async def read(identity: str, principal: User) -> dict[str, Any]:
    require_permission(principal, "read")
    result = await asyncio.to_thread(records.read, principal, identity)
    try:
        runtime = await client()
        handle = runtime.get_workflow_handle(identity)
        description = await handle.describe()
        result["runtime_status"] = description.status.name if description.status else "UNKNOWN"
        result["execution"] = await handle.query(ReportSourceWorkflow.status)
    except Exception:
        result["runtime_status"] = "UNOBSERVABLE"
    return result


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Literal["pause", "resume", "retry", "complete", "cancel"]
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: UUID


@router.post("/{identity}/control")
async def control(identity: str, request: Control, principal: User) -> dict[str, Any]:
    require_permission(principal, "read")
    require_permission(principal, "review" if request.command == "complete" else "ingest")
    record = await asyncio.to_thread(records.read, principal, identity)
    if request.command == "complete" and record["actor_id"] == principal.actor_id:
        raise WorkspaceError(403, "A different reviewer must acknowledge this source assessment")
    key = "control:" + str(request.idempotency_key)
    payload = {
        "node": "review",
        "command": request.command,
        "actor_id": principal.actor_id,
        "reason": request.reason,
    }
    previous = next((e for e in record["events"] if e["event_id"] == key), None)
    if previous and any(previous.get(k) != v for k, v in payload.items()):
        raise WorkspaceError(409, "Control identity already belongs to a different command")
    runtime = await client()
    handle = runtime.get_workflow_handle(identity)
    state = (await handle.query(ReportSourceWorkflow.status))["state"]
    if request.command == "complete" and state != "WAITING_REVIEW":
        raise WorkspaceError(409, "Assessment is not waiting for review")
    await asyncio.to_thread(records.event, principal, identity, key, payload)
    await handle.signal(ReportSourceWorkflow.control, {"id": key, "command": request.command})
    return {"workflow_id": identity, "command": request.command, "state": "SIGNALLED"}

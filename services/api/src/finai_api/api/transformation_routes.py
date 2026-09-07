"""Durable read-only builds over reviewed canonical transformation definitions."""

import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from finai_api.api.workflow_routes import client
from finai_api.domain.review import Principal
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import (
    function_catalog,
    report_workflows,
    transformation_history,
    transformation_runs,
)
from finai_api.services.workspace import WorkspaceError
from finai_api.transformation_workflow import TransformationWorkflow

router = APIRouter(prefix="/v1/ontology/transformations", tags=["durable evidence builds"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("")
def catalog(principal: User, after_resource_id: UUID | None = None) -> dict[str, Any]:
    return function_catalog.discover(
        principal, after_resource_id, resource_type="TransformationDefinition"
    )


@router.post("/runs")
async def start(principal: User, request: TransformationRunRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    require_permission(principal, "ingest")
    identity = await asyncio.to_thread(transformation_runs.retain, principal, request)
    runtime = await client()
    with suppress(WorkflowAlreadyStartedError):
        await runtime.start_workflow(
            TransformationWorkflow.run,
            {
                "workflow_id": identity,
                "actor_id": principal.actor_id,
                "scope": principal.scope.model_dump(mode="json"),
            },
            id=identity,
            task_queue="g8-report-source-v1",
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    return {
        "workflow_id": identity,
        "request_id": str(request.request_id),
        "state": "START_REQUEST_RECORDED",
        "business_effect_authorized": False,
    }


@router.get("/runs")
def history(
    principal: User,
    limit: int = Query(default=20, ge=1, le=50),
    before_created_at: datetime | None = None,
    before_request_id: UUID | None = None,
) -> dict[str, Any]:
    return transformation_history.discover(principal, limit, before_created_at, before_request_id)


@router.get("/runs/{request_id}")
async def read(principal: User, request_id: UUID) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    identity = f"transformation:{request_id}"
    result = await asyncio.to_thread(transformation_runs.read, principal, identity)
    try:
        runtime = await client()
        handle = runtime.get_workflow_handle(identity)
        description = await handle.describe()
        result["runtime_status"] = description.status.name if description.status else "UNKNOWN"
        result["execution"] = await handle.query(TransformationWorkflow.status)
    except Exception:
        result["runtime_status"] = "UNOBSERVABLE"
    return result


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Literal["pause", "resume", "cancel"]
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: UUID

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Control reason must contain at least ten non-padding characters")
        return value


@router.post("/runs/{request_id}/control")
async def control(principal: User, request_id: UUID, request: Control) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    require_permission(principal, "ingest")
    identity = f"transformation:{request_id}"
    record = await asyncio.to_thread(transformation_runs.read, principal, identity)
    key = "control:" + str(request.idempotency_key)
    payload = {"command": request.command, "actor_id": principal.actor_id, "reason": request.reason}
    previous = next((event for event in record["events"] if event["event_id"] == key), None)
    if previous and any(previous.get(name) != value for name, value in payload.items()):
        raise WorkspaceError(409, "Control identity already belongs to another command")
    runtime = await client()
    handle = runtime.get_workflow_handle(identity)
    description = await handle.describe()
    if description.status is None or description.status.name != "RUNNING":
        raise WorkspaceError(409, "Build is not running; retained results remain available")
    await asyncio.to_thread(report_workflows.event, principal, identity, key, payload)
    await handle.signal(TransformationWorkflow.control, {"id": key, "command": request.command})
    return {"request_id": str(request_id), "command": request.command, "state": "SIGNALLED"}

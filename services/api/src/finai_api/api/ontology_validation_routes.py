"""Reviewed profiles and durable validation reports over shared G8 authorities."""

import asyncio
from contextlib import suppress
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field, field_validator
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from finai_api.api.workflow_routes import client
from finai_api.config import get_settings
from finai_api.domain.external_ontology import Model
from finai_api.domain.ontology_validation import (
    ConstraintProfileDefinition,
    OntologyProfileDefinition,
    ValidationRunRequest,
)
from finai_api.domain.resources import ProposalDetail
from finai_api.domain.review import Principal
from finai_api.ontology_validation_workflow import OntologyValidationWorkflow
from finai_api.security import authenticated_principal
from finai_api.services import ontology_import, ontology_profiles, ontology_validation_runs

router = APIRouter(prefix="/v1/ontology/external", tags=["reviewed semantic validation"])
User = Annotated[Principal, Depends(authenticated_principal)]


def runtime_id(principal: Principal, identity: str) -> str:
    """Scope the transport identity without changing the canonical retained request ID."""
    return "ontology-validation-runtime:" + ontology_import.digest(
        {
            "workflow_id": identity,
            "scope": principal.scope.model_dump(mode="json"),
            "actor_id": principal.actor_id,
        }
    )


@router.post("/profiles/proposals")
def propose_profile(principal: User, request: OntologyProfileDefinition) -> ProposalDetail:
    return ontology_profiles.propose_profile(principal, request)


@router.post("/constraint-profiles/proposals")
def propose_constraints(principal: User, request: ConstraintProfileDefinition) -> ProposalDetail:
    return ontology_profiles.propose_constraint_profile(principal, request)


@router.post("/validation/runs", status_code=202)
async def start(principal: User, request: ValidationRunRequest) -> dict[str, Any]:
    identity = await asyncio.to_thread(ontology_validation_runs.retain, principal, request)
    dispatched = False
    try:
        runtime = await client()
        with suppress(WorkflowAlreadyStartedError):
            await asyncio.wait_for(
                runtime.start_workflow(
                    OntologyValidationWorkflow.run,
                    {
                        "workflow_id": identity,
                        "actor_id": principal.actor_id,
                        "scope": principal.scope.model_dump(mode="json"),
                    },
                    id=runtime_id(principal, identity),
                    task_queue=get_settings().temporal_task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                ),
                timeout=5,
            )
        dispatched = True
    except Exception:
        # Retained intent survives an unavailable runtime or a lost acknowledgement.
        # Retrying this exact request safely reuses the same workflow identity.
        pass
    return {
        "workflow_id": identity,
        "request_id": str(request.request_id),
        "request_sha256": ontology_import.digest(request.model_dump(mode="json")),
        "scope": principal.scope.model_dump(mode="json"),
        "state": "START_REQUEST_RECORDED" if dispatched else "RETAINED_DISPATCH_UNOBSERVABLE",
        "redispatch": "RETRY_SAME_REQUEST",
        "automatic_outbox_dispatch": False,
        "business_effect_authorized": False,
    }


@router.get("/validation/runs/{request_id}")
async def read(principal: User, request_id: UUID) -> dict[str, Any]:
    identity = f"ontology-validation:{request_id}"
    result = await asyncio.to_thread(ontology_validation_runs.read, principal, identity)
    try:
        runtime = await client()
        handle = runtime.get_workflow_handle(runtime_id(principal, identity))
        description = await asyncio.wait_for(handle.describe(), timeout=5)
        result["runtime_status"] = description.status.name if description.status else "UNKNOWN"
        result["execution"] = await asyncio.wait_for(
            handle.query(OntologyValidationWorkflow.status), timeout=5
        )
    except Exception:
        result["runtime_status"] = "UNOBSERVABLE"
    return result


@router.post("/validation/runs/{request_id}/report-proposals")
def propose_report(principal: User, request_id: UUID) -> ProposalDetail:
    return ontology_profiles.propose_report(principal, f"ontology-validation:{request_id}")


class Cancellation(Model):
    command_id: UUID
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("reason")
    @classmethod
    def substantive(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Cancellation requires a substantive reason")
        return value.strip()


@router.post("/validation/runs/{request_id}/cancel")
async def cancel(principal: User, request_id: UUID, request: Cancellation) -> dict[str, Any]:
    identity = f"ontology-validation:{request_id}"
    result = await asyncio.to_thread(
        ontology_validation_runs.cancel, principal, identity, request.command_id, request.reason
    )
    notified = False
    try:
        runtime = await client()
        await asyncio.wait_for(
            runtime.get_workflow_handle(runtime_id(principal, identity)).cancel(), timeout=5
        )
        notified = True
    except Exception:
        pass
    return {
        "cancellation": result,
        "request_id": str(request_id),
        "command_id": str(request.command_id),
        "scope": principal.scope.model_dump(mode="json"),
        "runtime_notified": notified,
        "business_effect_authorized": False,
    }

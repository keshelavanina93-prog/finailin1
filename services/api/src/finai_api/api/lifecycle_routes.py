from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from finai_api.domain.resource_lifecycle import (
    ConsumptionRequest,
    LifecycleRequest,
    LifecycleReview,
    VersionReference,
)
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import resource_lifecycle as lifecycle

router = APIRouter(prefix="/v1/ontology/lifecycle", tags=["version authority"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.post("/requests")
def request_transition(principal: User, request: LifecycleRequest) -> dict[str, Any]:
    return lifecycle.request_transition(principal, request)


@router.post("/requests/{request_id}/review")
def review_transition(
    principal: User, request_id: UUID, request: LifecycleReview
) -> dict[str, Any]:
    return lifecycle.review_transition(principal, request_id, request)


@router.get("/versions/{version_id}")
def history(principal: User, version_id: UUID, resource_id: UUID) -> dict[str, Any]:
    return lifecycle.history(
        principal, VersionReference(resource_id=resource_id, version_id=version_id)
    )


@router.post("/consume")
def consume(principal: User, request: ConsumptionRequest) -> dict[str, Any]:
    return lifecycle.consume(principal, request)

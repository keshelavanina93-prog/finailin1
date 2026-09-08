"""Immutable Metric observations over exact retained shared Function invocations."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from finai_api.domain.metric_execution import ObserveRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import metric_execution

router = APIRouter(prefix="/v1/ontology/metrics", tags=["retained metric observations"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("")
def catalog(
    principal: User,
    after_resource_id: UUID | None = None,
    function_resource_id: UUID | None = None,
    function_version_id: UUID | None = None,
    function_content_hash: str | None = None,
) -> dict[str, Any]:
    return metric_execution.discover(
        principal,
        after_resource_id,
        function_resource_id=function_resource_id,
        function_version_id=function_version_id,
        function_content_hash=function_content_hash,
    )


@router.post("/observations")
def observe(principal: User, request: ObserveRequest) -> dict[str, Any]:
    return metric_execution.observe(principal, request)


@router.get("/observations/{observation_id}")
def history(principal: User, observation_id: str) -> dict[str, Any]:
    return metric_execution.history(principal, observation_id)

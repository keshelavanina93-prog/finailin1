"""Immutable Metric observations over exact retained shared Function invocations."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from finai_api.domain.metric_execution import ObserveRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import metric_execution

router = APIRouter(prefix="/v1/ontology/metrics", tags=["retained metric observations"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.post("/observations")
def observe(principal: User, request: ObserveRequest) -> dict[str, Any]:
    return metric_execution.observe(principal, request)


@router.get("/observations/{observation_id}")
def history(principal: User, observation_id: str) -> dict[str, Any]:
    return metric_execution.history(principal, observation_id)

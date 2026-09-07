from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query

from finai_api.api.ontology_routes import User
from finai_api.services import runtime_observations as observations

router = APIRouter(prefix="/v1/ontology/runtime-observations", tags=["runtime observation"])


@router.post("")
def capture(principal: User, request: observations.ObservationRequest):
    return observations.capture(principal, request)


@router.get("")
def listing(
    principal: User,
    limit: int = Query(default=20, ge=1, le=50),
    before_recorded_at: datetime | None = None,
    before_request_id: UUID | None = None,
):
    return observations.listing(principal, limit, before_recorded_at, before_request_id)


@router.get("/{request_id}")
def history(principal: User, request_id: UUID):
    return observations.history(principal, request_id)

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query

from finai_api.api.ontology_routes import User
from finai_api.services.proposal_queue import page

router = APIRouter(prefix="/v1/ontology/proposal-queue", tags=["proposal discovery"])


@router.get("")
def proposal_queue(
    principal: User,
    limit: int = Query(default=25, ge=1, le=100),
    snapshot_at: datetime | None = None,
    before_created_at: datetime | None = None,
    before_proposal_id: UUID | None = None,
):
    return page(principal, limit, snapshot_at, before_created_at, before_proposal_id)

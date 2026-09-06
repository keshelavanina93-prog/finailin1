from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query

from finai_api.api.ontology_routes import User
from finai_api.services.history_search import search

router = APIRouter(prefix="/v1/ontology/history-search", tags=["historical discovery"])


@router.get("")
def history_search(
    principal: User,
    company_id: UUID,
    q: str = Query(default="", max_length=200),
    object_type: str | None = Query(default=None, max_length=100),
    effective_at: datetime | None = None,
    known_at: datetime | None = None,
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=50, ge=1, le=100),
):
    return search(principal, company_id, q, object_type, effective_at, known_at, offset, limit)

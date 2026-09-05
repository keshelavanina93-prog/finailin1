from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from finai_api.domain.review import Principal
from finai_api.domain.source_event import SourceEvent
from finai_api.security import authenticated_principal
from finai_api.services import event_time

router = APIRouter(prefix="/v1/ontology/event-time", tags=["retained event observations"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.post("/events")
def retain(principal: User, request: SourceEvent) -> dict[str, Any]:
    return event_time.retain_event(principal, request)


@router.get("/streams/{stream_id}/replay")
def replay(
    principal: User, stream_id: UUID, known_at: datetime, include_late: bool = False
) -> dict[str, Any]:
    return event_time.replay(principal, stream_id, known_at, include_late)

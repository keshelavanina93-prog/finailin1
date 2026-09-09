"""NYX citation and refusal boundary."""

from typing import Annotated

from fastapi import APIRouter, Depends

from finai_api.domain.nyx_reasoning import ReasonRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import nyx_reasoning

router = APIRouter(prefix="/v1/ontology/nyx", tags=["NYX reasoning"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.post("/reason")
def reason(principal: User, request: ReasonRequest) -> dict:
    return nyx_reasoning.reason(principal, request)

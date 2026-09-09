"""Exact-scope planning catalog and deterministic comparison endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import planning

router = APIRouter(prefix="/v1/ontology/planning", tags=["planning"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("/catalog")
def catalog(principal: User) -> dict[str, Any]:
    return planning.catalog(principal)


@router.get("/compare")
def compare(principal: User, scenario_a: UUID, scenario_b: UUID) -> dict[str, Any]:
    return planning.compare(principal, scenario_a, scenario_b)

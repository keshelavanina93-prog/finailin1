"""Discover reviewed financial capabilities without deriving financial values."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import company_financial_results

router = APIRouter(prefix="/v1/ontology/company-financial-results", tags=["company finance"])


@router.get("")
def discover(
    principal: Annotated[Principal, Depends(authenticated_principal)],
    company_id: UUID,
    valid_at: AwareDatetime | None = None,
    known_at: AwareDatetime | None = None,
    after_function_id: UUID | None = None,
    after_invocation_id: UUID | None = None,
) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return company_financial_results.discover(
        principal,
        company_id,
        valid_at=valid_at,
        known_at=known_at,
        after_function_id=after_function_id,
        after_invocation_id=after_invocation_id,
    )

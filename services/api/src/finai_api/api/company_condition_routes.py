from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime

from finai_api.domain.company_condition import CompanyConditionDescriptor
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services.company_condition import describe

router = APIRouter(prefix="/v1/ontology/company-condition", tags=["company condition"])


@router.get("", response_model=CompanyConditionDescriptor)
def company_condition(
    principal: Annotated[Principal, Depends(authenticated_principal)], company_id: UUID,
    valid_at: AwareDatetime | None = None, known_at: AwareDatetime | None = None,
) -> CompanyConditionDescriptor:
    return describe(principal, company_id, valid_at, known_at)

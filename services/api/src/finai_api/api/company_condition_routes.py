from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from finai_api.domain.company_condition import (
    CompanyConditionDescriptor,
    CompanyConditionDescriptorV2,
)
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services.company_condition import describe

router = APIRouter(prefix="/v1/ontology/company-condition", tags=["company condition"])


@router.get("", response_model=CompanyConditionDescriptor | CompanyConditionDescriptorV2)
def company_condition(
    principal: Annotated[Principal, Depends(authenticated_principal)],
    company_id: UUID,
    valid_at: AwareDatetime | None = None,
    known_at: AwareDatetime | None = None,
    contract_version: Annotated[int, Query(ge=1, le=2)] = 1,
) -> CompanyConditionDescriptor | CompanyConditionDescriptorV2:
    if contract_version == 1:
        return describe(principal, company_id, valid_at, known_at)
    return describe(principal, company_id, valid_at, known_at, contract_version=2)

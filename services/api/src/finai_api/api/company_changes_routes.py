from typing import Annotated

from fastapi import APIRouter, Depends

from finai_api.domain.company_changes import CompanyChangesDescriptor, CompanyChangesRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services.company_changes import compare

router = APIRouter(prefix="/v1/ontology/company-changes", tags=["retained company changes"])


@router.post("", response_model=CompanyChangesDescriptor)
def company_changes(
    principal: Annotated[Principal, Depends(authenticated_principal)],
    request: CompanyChangesRequest,
) -> CompanyChangesDescriptor:
    return compare(principal, request)

"""Company Home is a read-only projection; selecting a result never executes it."""

from typing import Annotated

from fastapi import APIRouter, Depends

from finai_api.domain.company_home import CompanyHomeDescriptor, CompanyHomeRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services.company_home import describe

router = APIRouter(prefix="/v1/ontology/company-home", tags=["company Home"])


@router.post("", response_model=CompanyHomeDescriptor)
def company_home(
    principal: Annotated[Principal, Depends(authenticated_principal)], request: CompanyHomeRequest
) -> CompanyHomeDescriptor:
    return describe(principal, request)

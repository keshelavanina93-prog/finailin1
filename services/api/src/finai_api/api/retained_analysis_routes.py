"""Read retained source-analysis references without creating a new execution."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from finai_api.domain.retained_analyses import RetainedAnalysisPage
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services.retained_analyses import discover

router = APIRouter(prefix="/v1/ontology/retained-analyses", tags=["retained analyses"])


@router.get("", response_model=RetainedAnalysisPage)
def retained_analyses(
    principal: Annotated[Principal, Depends(authenticated_principal)],
    company_id: UUID,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> RetainedAnalysisPage:
    return discover(principal, company_id, cursor)

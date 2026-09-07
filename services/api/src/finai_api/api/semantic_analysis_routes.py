from typing import Annotated

from fastapi import APIRouter, Depends

from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Projection, ProjectionRequest
from finai_api.security import authenticated_principal
from finai_api.services.semantic_analysis import project

router = APIRouter(prefix="/v1/ontology/analysis", tags=["semantic analysis workspace"])


@router.post("/project", response_model=Projection)
def projection(
    principal: Annotated[Principal, Depends(authenticated_principal)], request: ProjectionRequest
) -> Projection:
    return project(principal, request)

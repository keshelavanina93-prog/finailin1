from typing import Annotated

from fastapi import APIRouter, Depends

from finai_api.domain.object_sets import ObjectSetQuery, ObjectSetResult
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services.object_sets import query_objects

router = APIRouter(prefix="/v1/ontology/object-sets", tags=["ontology queries"])


@router.post("/query", response_model=ObjectSetResult)
def query(
    principal: Annotated[Principal, Depends(authenticated_principal)],
    request: ObjectSetQuery,
) -> ObjectSetResult:
    return query_objects(principal, request)

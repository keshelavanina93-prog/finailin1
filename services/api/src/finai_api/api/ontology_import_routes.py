"""External ontology imports prepare shared review proposals; they never approve them."""

from typing import Annotated

from fastapi import APIRouter, Depends

from finai_api.domain.external_ontology import (
    ImportRequest,
    ReleaseInspectionRequest,
    SourceDefinition,
    TermInspectionRequest,
)
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import external_ontology_queries, ontology_import

router = APIRouter(prefix="/v1/ontology/external", tags=["governed external ontology imports"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.post("/sources/proposals")
def propose_source(principal: User, request: SourceDefinition):
    return ontology_import.propose_source(principal, request)


@router.post("/imports/proposals")
def prepare_import(principal: User, request: ImportRequest):
    return ontology_import.prepare(principal, request)


@router.post("/releases/inspect")
def inspect_release(principal: User, request: ReleaseInspectionRequest):
    return external_ontology_queries.release_metadata(principal, request)


@router.post("/index/rebuild")
def rebuild_index(principal: User, request: ReleaseInspectionRequest):
    return external_ontology_queries.project(principal, request, rebuild=True)


@router.post("/terms/inspect")
def inspect_term(principal: User, request: TermInspectionRequest):
    return external_ontology_queries.project(principal, request, rebuild=False)

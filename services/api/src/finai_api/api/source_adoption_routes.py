"""Review and inspect shared recurring-source contracts through canonical proposals."""

from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.source_adoption import SourceAdoptionSelection, SourceFamilySelection
from finai_api.services import source_adoption

router = APIRouter(prefix="/v1/ontology/source-adoption", tags=["recurring source authority"])


@router.post("/families/inspect")
def inspect_family(principal: User, request: SourceFamilySelection):
    return source_adoption.prepare(principal, request)


@router.post("/families/proposal")
def propose_family(principal: User, request: SourceFamilySelection):
    return source_adoption.propose(principal, request)


@router.post("/transitions/inspect")
def inspect_transition(principal: User, request: SourceAdoptionSelection):
    return source_adoption.prepare(principal, request)


@router.post("/transitions/proposal")
def propose_transition(principal: User, request: SourceAdoptionSelection):
    return source_adoption.propose(principal, request)


@router.post("/successor")
def read_successor(principal: User, request: VersionReference):
    return source_adoption.read_successor(principal, request)

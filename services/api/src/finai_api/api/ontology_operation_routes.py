from uuid import UUID

from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.domain.investigation import InvestigationAction
from finai_api.domain.investigation_resolution import InvestigationResolutionAction
from finai_api.services import investigation_actions, investigation_resolution
from finai_api.services import ontology_operations as operations

router = APIRouter(prefix="/v1/ontology/operations", tags=["ontology operation execution"])


@router.get("")
def recent(principal: User, document_id: str | None = None, binding_id: UUID | None = None):
    return operations.recent(principal, document_id, binding_id)


@router.post("/bindings")
def invoke(principal: User, request: operations.BindingAction):
    return operations.invoke(principal, request)


@router.post("/investigations")
def investigate(principal: User, request: InvestigationAction):
    return investigation_actions.invoke(principal, request)


@router.post("/investigation-resolutions")
def resolve_investigation(principal: User, request: InvestigationResolutionAction):
    return investigation_resolution.invoke(principal, request)


@router.get("/{identity}")
def read(principal: User, identity: str):
    return operations.read(principal, identity)


@router.post("/licence-notices")
def licence_notice(principal: User, request: operations.LicenceAction):
    return operations.invoke(principal, request)


@router.post("/{identity}/resume")
def resume(principal: User, identity: str):
    return operations.resume(principal, identity)

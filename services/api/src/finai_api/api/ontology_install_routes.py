from uuid import UUID

from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.security import require_permission
from finai_api.services import ontology_install

router = APIRouter(prefix="/v1/ontology/install", tags=["ontology installation"])


@router.get("/preflight")
def install_preflight(principal: User) -> dict:
    require_permission(principal, "ontology_admin")
    return ontology_install.preflight(principal)


@router.get("/steward-grant")
def steward_grant(principal: User) -> dict:
    require_permission(principal, "ontology_admin")
    return ontology_install.grant_status(principal)


@router.post("/steward-grant")
def request_steward_grant(
    principal: User, request: ontology_install.StewardGrantRequest
) -> dict:
    require_permission(principal, "ontology_admin")
    require_permission(principal, "ontology_propose")
    return ontology_install.request_steward_grant(principal, request)


@router.post("/steward-grant/{grant_id}/decision")
def review_steward_grant(
    principal: User,
    grant_id: UUID,
    request: ontology_install.StewardGrantDecision,
) -> dict:
    require_permission(principal, "ontology_admin")
    require_permission(principal, "ontology_review")
    return ontology_install.review_steward_grant(principal, grant_id, request)

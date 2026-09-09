from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.security import require_permission
from finai_api.services import ontology_install

router = APIRouter(prefix="/v1/ontology/install", tags=["ontology installation"])


@router.get("/preflight")
def install_preflight(principal: User) -> dict:
    require_permission(principal, "ontology_admin")
    return ontology_install.preflight(principal)

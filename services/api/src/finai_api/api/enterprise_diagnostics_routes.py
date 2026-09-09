"""Read-only enterprise target diagnosis over the caller's authorized resource graph."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from finai_api.domain.enterprise_diagnostics import DiagnosticRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import enterprise_diagnostics

router = APIRouter(prefix="/v1/workspace", tags=["enterprise diagnostics"])


def reader(principal: Annotated[Principal, Depends(authenticated_principal)]) -> Principal:
    require_permission(principal, "read")
    require_permission(principal, "ontology_read")
    return principal


User = Annotated[Principal, Depends(reader)]


@router.get("/diagnostic-targets")
def diagnostic_targets(principal: User, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return enterprise_diagnostics.catalog()


@router.post("/diagnostics")
def diagnose_target(
    request: DiagnosticRequest, principal: User, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return enterprise_diagnostics.diagnose(principal, request)

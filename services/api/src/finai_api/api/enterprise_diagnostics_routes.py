"""Read-only enterprise target diagnosis over the caller's authorized resource graph."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from finai_api.domain.enterprise_diagnostics import DiagnosticRequest
from finai_api.domain.executable_enterprise_model import (
    ExecutablePreflightRequest,
    resolve_function,
)
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import enterprise_diagnostics

router = APIRouter(prefix="/v1/workspace", tags=["enterprise diagnostics"])


def reader(principal: Annotated[Principal, Depends(authenticated_principal)]) -> Principal:
    require_permission(principal, "read")
    require_permission(principal, "ontology_read")
    return principal


User = Annotated[Principal, Depends(reader)]


def preflight_reader(
    principal: Annotated[Principal, Depends(authenticated_principal)],
) -> Principal:
    """A preflight is a read-only contract evaluation, not ontology discovery."""

    require_permission(principal, "read")
    return principal


ReadUser = Annotated[Principal, Depends(preflight_reader)]


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


@router.post("/executable-preflight")
def executable_preflight(
    request: ExecutablePreflightRequest, principal: ReadUser, response: Response
) -> dict[str, object]:
    """Evaluate an executable dependency contract without changing enterprise state."""

    response.headers["Cache-Control"] = "no-store"
    result = resolve_function(request.function, request.available)
    return {"preflight": result.model_dump(mode="json"), "authority_effect": "NONE"}

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
from finai_api.services import enterprise_diagnostics, executable_function_registry

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
    function = (
        executable_function_registry.get_registered_function(request.function_id)
        if request.function_id is not None
        else request.function
    )
    assert function is not None
    result = resolve_function(function, request.available)
    return {
        "preflight": result.model_dump(mode="json"),
        "function": function.model_dump(mode="json"),
        "registry_state": (
            "AUTHORITATIVE_REGISTERED"
            if request.function_id is not None
            else "REQUEST_SUPPLIED_CONTRACT"
        ),
        "authority_effect": "NONE",
    }


@router.get("/executable-functions")
def executable_functions(principal: ReadUser, response: Response) -> dict[str, object]:
    """List server-registered executable verbs without executing any verb."""

    response.headers["Cache-Control"] = "no-store"
    return {
        "contract": "executable-function-registry/1",
        "functions": [
            item.model_dump(mode="json")
            for item in executable_function_registry.list_registered_functions()
        ],
        "authority_effect": "NONE",
    }

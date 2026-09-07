"""Shared, reviewed read-only analysis execution and retained invocation evidence."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import function_catalog, function_execution, function_invocations

router = APIRouter(prefix="/v1/ontology/functions", tags=["saved analysis execution"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("")
def catalog(principal: User, after_resource_id: UUID | None = None) -> dict[str, Any]:
    return function_catalog.discover(principal, after_resource_id)


@router.get("/implementation")
def implementation(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return function_execution.manifest()


@router.post("/invocations")
def invoke(principal: User, request: FunctionInvocation) -> dict[str, Any]:
    return function_invocations.invoke(principal, request)


@router.get("/invocations/{request_id}")
def history(principal: User, request_id: UUID) -> dict[str, Any]:
    return function_invocations.history(principal, request_id)

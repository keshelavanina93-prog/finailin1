"""Explicit retention and exact historical reads of source reconciliation exceptions."""

from typing import Annotated, Any

from fastapi import APIRouter, Path

from finai_api.api.ontology_routes import User
from finai_api.domain.source_reconciliation_exception import SourceExceptionRequest
from finai_api.services import source_reconciliation_exception

router = APIRouter(prefix="/v1/ontology/source-exceptions", tags=["source exceptions"])
RunId = Annotated[str, Path(pattern=r"^fcr_[a-f0-9]{64}$")]


@router.post("")
def retain(principal: User, request: SourceExceptionRequest) -> dict[str, Any]:
    return source_reconciliation_exception.retain(principal, request)


@router.get("/{run_id}")
def read(principal: User, run_id: RunId) -> dict[str, Any]:
    return source_reconciliation_exception.read(principal, run_id)

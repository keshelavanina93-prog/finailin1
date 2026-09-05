import csv
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from finai_api.config import get_settings
from finai_api.domain.authority import CompileHydrationRequest, ConstructionReceipt, ExactScope
from finai_api.domain.ingest import IngestReceipt, IngestRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, authorized_scope, require_permission
from finai_api.services.authority_compiler import AuthorityCompiler
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source
from finai_api.services.resources import context_binding
from finai_api.storage import retain, retrieve

router = APIRouter()
compiler = AuthorityCompiler()


@router.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.service_name,
        "version": settings.api_version,
        "environment": settings.environment,
    }


@router.post(
    "/v1/hydration/compile",
    response_model=ConstructionReceipt,
    tags=["enterprise hydration"],
)
def compile_hydration(
    request: CompileHydrationRequest,
    scope: Annotated[ExactScope, Depends(authorized_scope)],
) -> ConstructionReceipt:
    if request.authority_contract.scope != scope:
        raise HTTPException(403, "Exact scope does not match credential")
    return compiler.compile(request)


@router.post("/v1/hydration/ingest", response_model=IngestReceipt, tags=["enterprise hydration"])
def ingest(
    request: IngestRequest,
    principal: Annotated[Principal, Depends(authenticated_principal)],
) -> IngestReceipt:
    require_permission(principal, "ingest")
    scope = principal.scope
    if request.scope != scope:
        raise HTTPException(403, "Exact scope does not match credential")
    context = context_binding(principal) if request.context_version_id else None
    if context and (
        not context["binding"]
        or context["binding"]["version_id"] != str(request.context_version_id)
    ):
        raise HTTPException(409, "Canonical accounting context changed; refresh before ingestion")
    try:
        receipt = compile_source(request)
        if context:
            receipt = receipt.model_copy(
                update={
                    "context_version_id": request.context_version_id,
                    "canonical_references": context["canonical_references"],
                }
            )
    except SourceAuthorityDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return retain(request, receipt, principal.actor_id)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(503, "Evidence store unavailable; no receipt accepted") from exc


@router.get("/v1/hydration/receipts/{receipt_id}", response_model=IngestReceipt)
def receipt_detail(
    receipt_id: str,
    scope: Annotated[ExactScope, Depends(authorized_scope)],
) -> IngestReceipt:
    try:
        receipt = retrieve(scope, receipt_id)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(503, "Evidence store unavailable") from exc
    if receipt is None:
        raise HTTPException(404, "Receipt not found in authorized scope")
    return receipt

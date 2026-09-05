import csv
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from finai_api.config import get_settings
from finai_api.domain.authority import CompileHydrationRequest, ConstructionReceipt, ExactScope
from finai_api.domain.ingest import IngestReceipt, IngestRequest
from finai_api.security import authorized_scope
from finai_api.services.authority_compiler import AuthorityCompiler
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source
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
    scope: Annotated[ExactScope, Depends(authorized_scope)],
) -> IngestReceipt:
    if request.scope != scope:
        raise HTTPException(403, "Exact scope does not match credential")
    try:
        receipt = compile_source(request)
    except SourceAuthorityDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except (ValueError, csv.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return retain(request, receipt)
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

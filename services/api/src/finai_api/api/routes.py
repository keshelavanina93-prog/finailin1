import csv
from datetime import UTC, datetime
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response

from finai_api.config import get_settings
from finai_api.domain.authority import CompileHydrationRequest, ConstructionReceipt, ExactScope
from finai_api.domain.ingest import IngestReceipt, IngestRequest
from finai_api.domain.review import Principal
from finai_api.evidence_objects import EvidenceStoreUnavailable, check_ready
from finai_api.security import authenticated_principal, authorized_scope, require_permission
from finai_api.services.authority_compiler import AuthorityCompiler
from finai_api.services.ingest_binding import bind_receipt
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source
from finai_api.storage import retain, retrieve

router = APIRouter()
compiler = AuthorityCompiler()
REQUIRED_SCHEMA_VERSION = 46


@router.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.service_name,
        "version": settings.api_version,
        "environment": settings.environment,
    }


@router.get("/ready", tags=["operations"])
def readiness(response: Response) -> dict[str, str]:
    status = {"database": "unavailable", "schema": "unavailable", "evidence_store": "unavailable"}
    dsn = get_settings().database_url.get_secret_value()
    if dsn:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT source_storage FROM hydration_runs LIMIT 0")
                applied = conn.execute("SELECT version FROM schema_migrations").fetchall()
                if set(range(1, REQUIRED_SCHEMA_VERSION + 1)).issubset({row[0] for row in applied}):
                    status["schema"] = "ready"
                else:
                    status["schema"] = "migration_required"
            status["database"] = "ready"
        except psycopg.Error:
            pass
    try:
        check_ready()
        status["evidence_store"] = "ready"
    except EvidenceStoreUnavailable:
        pass
    ready = all(value == "ready" for value in status.values())
    response.status_code = 200 if ready else 503
    return {"status": "ready" if ready else "unavailable", **status}


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
    try:
        started = datetime.now(UTC).isoformat()
        receipt = bind_receipt(principal, request, compile_source(request))
        receipt = receipt.model_copy(
            update={
                "process_steps": (
                    {
                        "id": "inspect",
                        "state": "COMPLETED",
                        "depends_on": [],
                        "started_at": started,
                        "completed_at": datetime.now(UTC).isoformat(),
                        "function": receipt.classifier_version,
                        "input_ids": [receipt.source_sha256],
                        "output_ids": [receipt.receipt_id],
                        "operations": list(receipt.functions_executed),
                        "mapping_version": receipt.authority_contract_version,
                        "warning_count": len(receipt.warnings),
                        "reject_count": len(receipt.rejects),
                    },
                )
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

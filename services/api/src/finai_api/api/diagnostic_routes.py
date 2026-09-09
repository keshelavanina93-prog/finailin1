"""Read-only runtime checks used by the evidence and NYX context panels."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission

router = APIRouter(prefix="/v1/diagnostics", tags=["diagnostics"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("/readiness")
def readiness(principal: User) -> dict[str, object]:
    """Expose route and scope capabilities without probing or mutating storage."""

    require_permission(principal, "read")
    return {
        "service": "historical-trial-balance-intake",
        "status": "ROUTE_REGISTERED",
        "active_runtime_period": principal.scope.period,
        "registered_routes": [
            "/v1/hydration/trial-balance-package",
            "/v1/workspace/constructions/{receipt_id}?period=2025-MM",
            "/v1/diagnostics/readiness",
            "/v1/diagnostics/evidence-context",
        ],
        "checks": {
            "historical_scope_guard": True,
            "source_period_binding": True,
            "async_off_event_loop": True,
            "durable_job_state": False,
            "nyx_scope_context_route": True,
            "nyx_retained_evidence_probe": "NOT_RUN",
        },
        "storage_probe": "NOT_RUN",
    }


@router.get("/evidence-context")
def evidence_context(
    principal: User,
    source_year: Annotated[int, Query(ge=2000, le=2100)] = 2025,
) -> dict[str, object]:
    """Return the temporal facts NYX must display for historical evidence."""

    require_permission(principal, "read")
    if source_year != 2025:
        raise HTTPException(
            422, "This diagnostic context is scoped to the 2025 SGP historical package"
        )
    periods = [f"{source_year}-{month:02d}" for month in range(1, 13)]
    return {
        "source_year": str(source_year),
        "valid_periods": periods,
        "active_runtime_period": principal.scope.period,
        "evaluated_under_active_runtime_period": False,
        "period_binding": "SOURCE_PERIOD_PER_WORKBOOK",
        "source_use": "HISTORICAL_REFERENCE",
        "financial_facts_authorized": False,
        "mapping_state": "REQUIRED",
        "downstream_locks": ["Finance", "Planning", "Reporting"],
        "answer_basis": "RECORDED_EVIDENCE_ONLY",
        "context_state": "AVAILABLE_NOT_RETAINED_PROOF",
    }

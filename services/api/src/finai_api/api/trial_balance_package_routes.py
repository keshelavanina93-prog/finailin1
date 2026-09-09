"""Historical SGP trial-balance package intake."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from finai_api.domain.review import Principal
from finai_api.domain.trial_balance_package import (
    TrialBalancePackageDiagnostics,
    TrialBalancePackageDiagnosticsRequest,
    TrialBalancePackageReport,
    TrialBalancePackageRequest,
)
from finai_api.security import authenticated_principal, require_permission
from finai_api.services.trial_balance_package import (
    TrialBalancePackageError,
    compile_package,
    diagnose_package,
)

router = APIRouter(prefix="/v1/hydration", tags=["historical trial balance package"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.post("/trial-balance-package", response_model=TrialBalancePackageReport)
async def ingest_trial_balance_package(
    request: TrialBalancePackageRequest, principal: User
) -> TrialBalancePackageReport:
    """Compile twelve 2025 workbooks without borrowing the active runtime period.

    XLS parsing, source hashing and evidence retention run off the event loop so
    concurrent workspace requests remain responsive during a large package.
    """

    require_permission(principal, "ingest")
    try:
        return await asyncio.to_thread(compile_package, principal, request)
    except TrialBalancePackageError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, "Evidence store unavailable; no package accepted") from exc


@router.post(
    "/trial-balance-package/diagnostics",
    response_model=TrialBalancePackageDiagnostics,
)
def diagnose_trial_balance_package(
    request: TrialBalancePackageDiagnosticsRequest, principal: User
) -> TrialBalancePackageDiagnostics:
    """Inspect package controls in the caller's scope without mutating state."""

    require_permission(principal, "read")
    try:
        return diagnose_package(request.report, principal.scope)
    except TrialBalancePackageError as exc:
        raise HTTPException(403, str(exc)) from exc

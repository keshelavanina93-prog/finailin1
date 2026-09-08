from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from finai_api.api.ontology_routes import User
from finai_api.domain.journal_production import JournalProductionRequest
from finai_api.domain.resources import ResourceReview
from finai_api.services import company_journals

router = APIRouter(prefix="/v1/ontology/company-journals", tags=["company journal readback"])


@router.post("/production/preview")
def journal_preview(principal: User, request: JournalProductionRequest):
    from finai_api.services.journal_production import prepare

    return prepare(principal, request)[0]


@router.get("/production/attempts/{request_id}")
def journal_production_attempt(principal: User, request_id: UUID):
    from finai_api.services.journal_production_history import history
    from finai_api.services.workspace import WorkspaceError

    result = history(principal, request_id)
    if result is None:
        result = history(principal, request_id, "PREPARED")
    if result is None:
        raise WorkspaceError(404, "Journal production attempt unavailable in this scope")
    return result


@router.post("/production/proposals")
def journal_propose(principal: User, request: JournalProductionRequest):
    from finai_api.services.journal_production import submit

    return submit(principal, request)


@router.post("/production/proposals/{proposal_id}/review")
def journal_review(principal: User, proposal_id: UUID, request: ResourceReview):
    from finai_api.services.journal_production import check

    return check(principal, proposal_id, request)


@router.get("/reconciliation/source/{invocation_id}")
def source_reconciliation(
    principal: User,
    invocation_id: UUID,
    company_id: UUID,
    snapshot_at: datetime | None = None,
):
    from finai_api.services.journal_reconciliation import reconcile

    return reconcile(principal, invocation_id, company_id, snapshot_at)


@router.get("")
def journals(
    principal: User,
    company_id: UUID,
    ledger_id: UUID,
    book_id: UUID,
    period_id: UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    offset: Annotated[int, Query(ge=0, le=5000)] = 0,
    snapshot_at: datetime | None = None,
):
    return company_journals.list_journals(
        principal, company_id, ledger_id, book_id, period_id, limit, offset, snapshot_at
    )


@router.get("/{journal_id}")
def journal(
    principal: User,
    journal_id: UUID,
    version_id: UUID,
    company_id: UUID,
    ledger_id: UUID,
    book_id: UUID,
    period_id: UUID,
    snapshot_at: datetime | None = None,
):
    return company_journals.detail(
        principal, company_id, ledger_id, book_id, period_id, journal_id, version_id, snapshot_at
    )

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from finai_api.api.ontology_routes import User
from finai_api.services import company_journals

router = APIRouter(prefix="/v1/ontology/company-journals", tags=["company journal readback"])


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

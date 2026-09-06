from datetime import datetime
from uuid import UUID

from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.services.company_context import resolve

router = APIRouter(prefix="/v1/ontology/company-context", tags=["company ontology context"])


@router.get("")
def company_context(
    principal: User,
    company_id: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    ledger_id: UUID | None = None,
    book_id: UUID | None = None,
    period_id: UUID | None = None,
):
    return resolve(principal, company_id, valid_at, known_at, ledger_id, book_id, period_id)

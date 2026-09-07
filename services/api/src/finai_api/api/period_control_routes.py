from uuid import UUID

from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.services import period_control

router = APIRouter(prefix="/v1/ontology/period-control", tags=["period posting control"])


@router.get("")
def current(principal: User, company_id: UUID, ledger_id: UUID, book_id: UUID, period_id: UUID):
    return period_control.read(principal, company_id, ledger_id, book_id, period_id)


@router.post("/proposal")
def propose(principal: User, request: period_control.ProposalRequest):
    return period_control.propose(principal, request)

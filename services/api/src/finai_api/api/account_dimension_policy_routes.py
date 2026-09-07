from uuid import UUID

from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.services import account_dimension_policy

router = APIRouter(
    prefix="/v1/ontology/account-dimension-policy", tags=["account analytical policy"]
)


@router.get("")
def current(principal: User, company_id: UUID, account_id: UUID):
    return account_dimension_policy.read(principal, company_id, account_id)


@router.post("/proposal")
def propose(principal: User, request: account_dimension_policy.ProposalRequest):
    return account_dimension_policy.propose(principal, request)

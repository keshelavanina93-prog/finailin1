"""HTTP boundary for the generic 1C turnover trial-balance contract."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import tb_finance_contract

router = APIRouter(prefix="/v1/ontology/finance", tags=["finance ontology"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("/contracts/1c_turnover_trial_balance")
def trial_balance_contract(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return tb_finance_contract.contract_definition()


@router.post("/contracts/1c_turnover_trial_balance/validate")
def validate_trial_balance_contract(
    principal: User, request: tb_finance_contract.TbFinanceContractRequest
) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return tb_finance_contract.validate_input(request)

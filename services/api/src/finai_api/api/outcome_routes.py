"""Exact-scope outcome measurement endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import outcomes

router = APIRouter(prefix="/v1/ontology/outcomes", tags=["outcomes"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("/actual-vs-plan")
def actual_vs_plan(
    principal: User, plan_scenario_id: UUID, actual_scenario_id: UUID
) -> dict[str, Any]:
    return outcomes.actual_vs_plan(principal, plan_scenario_id, actual_scenario_id)


@router.get("/learning-evaluation")
def learning_evaluation(
    principal: User,
    plan_scenario_id: UUID,
    actual_scenario_id: UUID,
    tolerance: str = "0",
) -> dict[str, Any]:
    return outcomes.evaluate_learning(principal, plan_scenario_id, actual_scenario_id, tolerance)

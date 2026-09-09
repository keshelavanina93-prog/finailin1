"""Exact-scope outcome measurement endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

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


@router.post("/measurements")
def retain_measurement(measurement: dict[str, Any], principal: User) -> dict[str, Any]:
    return outcomes.retain_measurement(principal, measurement)


@router.get("/measurements")
def measurement_timeline(
    principal: User, limit: int = Query(default=50, ge=1, le=100)
) -> dict[str, Any]:
    return outcomes.measurement_timeline(principal, limit)

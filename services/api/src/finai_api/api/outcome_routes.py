"""Exact-scope outcome measurement endpoints."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

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


@router.get("/multi-baseline")
def multi_baseline(
    principal: User,
    actual_scenario_id: UUID,
    baseline_scenario_id: Annotated[list[UUID], Query(min_length=1, max_length=12)],
) -> dict[str, Any]:
    return outcomes.multi_baseline(principal, actual_scenario_id, tuple(baseline_scenario_id))


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


@router.post("/learning-candidates")
def retain_learning_candidate(evaluation: dict[str, Any], principal: User) -> dict[str, Any]:
    return outcomes.retain_learning_candidate(principal, evaluation)


class LearningCandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["PROMOTION_APPROVED", "REJECTED", "ROLLBACK_APPROVED"]
    rationale: str = Field(min_length=10, max_length=2000)


@router.post("/learning-candidates/{candidate_id}/decision")
def decide_learning_candidate(
    candidate_id: str, request: LearningCandidateDecision, principal: User
) -> dict[str, Any]:
    return outcomes.decide_learning_candidate(
        principal, candidate_id, request.decision, request.rationale
    )


@router.get("/learning-candidates")
def learning_candidate_timeline(
    principal: User, limit: int = Query(default=50, ge=1, le=100)
) -> dict[str, Any]:
    return outcomes.learning_candidate_timeline(principal, limit)

"""Reviewable plan metadata from the same compiler used to retain a build."""

from typing import Any

from finai_api.domain.review import Principal
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import transformation_definitions


def preview(principal: Principal, request: TransformationRunRequest) -> dict[str, Any]:
    compiled = transformation_definitions.plan(principal, request)
    return {
        "contract": "transformation-preview/1",
        "request": request.model_dump(mode="json"),
        "compiled_plan": compiled,
        "plan_hash": compiled["plan_hash"],
        "exact_scope": compiled["exact_scope"],
        "coverage": "PLAN_METADATA_ONLY",
        "transformed_rows_available": False,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }

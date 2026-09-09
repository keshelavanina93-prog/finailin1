"""Deterministic, evidence-bound outcome measurement over accepted plan facts."""

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from finai_api.security import require_permission
from finai_api.services import planning
from finai_api.services.workspace import WorkspaceError

DIMENSIONS = (
    "budget_article_id",
    "legal_entity_id",
    "period_id",
    "department_id",
    "measure",
    "warehouse_id",
    "unit_id",
    "currency_id",
)


def actual_vs_plan(principal, plan_scenario_id: UUID, actual_scenario_id: UUID) -> dict[str, Any]:
    """Measure accepted actual cells against accepted plan cells in one company scope.

    A ScenarioVersion is only treated as actual when its declared ``kind`` is
    ``ACTUAL`` (case-insensitive). The endpoint never promotes a scenario,
    recalculates a metric, or creates a learning candidate.
    """
    require_permission(principal, "ontology_read")
    company_id = str(principal.scope.legal_entity_id)
    scenarios = {
        str(row["resource_id"]): row
        for row in planning._resources(principal, "ScenarioVersion")
        if not row["attributes"].get("legal_entity_id")
        or str(row["attributes"].get("legal_entity_id")) == company_id
    }
    for scenario_id in (plan_scenario_id, actual_scenario_id):
        if str(scenario_id) not in scenarios:
            raise WorkspaceError(404, "Scenario is unavailable in the authorized company scope")
    actual_kind = str(scenarios[str(actual_scenario_id)]["attributes"].get("kind", "")).upper()
    if actual_kind != "ACTUAL":
        raise WorkspaceError(409, "Outcome measurement requires an ACTUAL scenario")

    grouped: dict[tuple[str, ...], dict[str, Decimal]] = {}
    wanted = {str(plan_scenario_id): "planned", str(actual_scenario_id): "actual"}
    for row in planning._resources(principal, "PlanningCellFact"):
        attrs = row["attributes"]
        if str(attrs.get("legal_entity_id")) != company_id:
            continue
        scenario = wanted.get(str(attrs.get("scenario_version_id")))
        if scenario is None:
            continue
        try:
            amount = Decimal(str(attrs["amount"]))
        except (InvalidOperation, KeyError) as exc:
            raise WorkspaceError(409, "Accepted planning cell contains an invalid amount") from exc
        key = tuple(str(attrs.get(name, "")) for name in DIMENSIONS)
        bucket = grouped.setdefault(key, {})
        bucket[scenario] = bucket.get(scenario, Decimal(0)) + amount

    rows = []
    for key, values in sorted(grouped.items()):
        planned = values.get("planned", Decimal(0))
        actual = values.get("actual", Decimal(0))
        variance = actual - planned
        rows.append(
            {
                "dimension": dict(zip(DIMENSIONS, key, strict=True)),
                "planned": format(planned, "f"),
                "actual": format(actual, "f"),
                "variance": format(variance, "f"),
            }
        )
    return {
        "contract": "outcome-measurement/1",
        "plan_scenario": scenarios[str(plan_scenario_id)],
        "actual_scenario": scenarios[str(actual_scenario_id)],
        "rows": rows,
        "coverage": "ACCEPTED_PLANNING_CELL_FACTS",
        "measurement_authorized": True,
        "learning_candidate_created": False,
        "policy_or_model_changed": False,
        "business_effect_authorized": False,
    }

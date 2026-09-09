"""Read-only planning projections over accepted, versioned canonical facts.

Planning does not invent a forecast in this module. It exposes the accepted
ScenarioVersion and PlanningCellFact resources already governed by the
ontology and performs deterministic, scope-bound scenario comparison. Draft
and forecast calculation remains a separate reviewed Function concern.
"""

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from finai_api.security import require_permission
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


def _resources(principal, object_type: str, limit: int = 1000) -> list[dict[str, Any]]:
    rows = resources.list_resources(principal, object_type, "", 0, limit=limit)
    return [row.model_dump(mode="json") for row in rows]


def catalog(principal) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    scenarios = _resources(principal, "ScenarioVersion")
    cells = _resources(principal, "PlanningCellFact")
    company_id = str(principal.scope.legal_entity_id)
    scoped_cells = [
        row for row in cells if str(row["attributes"].get("legal_entity_id")) == company_id
    ]
    scoped_scenarios = [
        row
        for row in scenarios
        if not row["attributes"].get("legal_entity_id")
        or str(row["attributes"].get("legal_entity_id")) == company_id
    ]
    return {
        "contract": "planning-catalog/1",
        "scenarios": scoped_scenarios,
        "cells": scoped_cells,
        "scope": {"tenant_id": str(principal.scope.tenant_id), "legal_entity_id": company_id},
        "authority": "ACCEPTED_CANONICAL_RESOURCES_ONLY",
        "forecast_calculation_available": False,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def compare(principal, scenario_a: UUID, scenario_b: UUID) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    company_id = str(principal.scope.legal_entity_id)
    scenarios = {
        str(row["resource_id"]): row
        for row in _resources(principal, "ScenarioVersion")
        if not row["attributes"].get("legal_entity_id")
        or str(row["attributes"].get("legal_entity_id")) == company_id
    }
    for scenario_id in (scenario_a, scenario_b):
        if str(scenario_id) not in scenarios:
            raise WorkspaceError(404, "Scenario is unavailable in the authorized company scope")
    cells = [
        row
        for row in _resources(principal, "PlanningCellFact")
        if str(row["attributes"].get("legal_entity_id")) == company_id
        and str(row["attributes"].get("scenario_version_id")) in {str(scenario_a), str(scenario_b)}
    ]
    grouped: dict[tuple[str, ...], dict[str, Decimal]] = {}
    for row in cells:
        attrs = row["attributes"]
        try:
            amount = Decimal(str(attrs["amount"]))
        except (InvalidOperation, KeyError) as exc:
            raise WorkspaceError(409, "Accepted planning cell contains an invalid amount") from exc
        key = tuple(
            str(attrs.get(name, ""))
            for name in (
                "budget_article_id",
                "legal_entity_id",
                "period_id",
                "department_id",
                "measure",
                "warehouse_id",
                "unit_id",
                "currency_id",
            )
        )
        bucket = grouped.setdefault(key, {})
        bucket[str(attrs["scenario_version_id"])] = bucket.get(
            str(attrs["scenario_version_id"]), Decimal(0)
        ) + amount
    rows = []
    for key, values in sorted(grouped.items()):
        a = values.get(str(scenario_a), Decimal(0))
        b = values.get(str(scenario_b), Decimal(0))
        rows.append(
            {
                "dimension": dict(
                    zip(
                        (
                            "budget_article_id",
                            "legal_entity_id",
                            "period_id",
                            "department_id",
                            "measure",
                            "warehouse_id",
                            "unit_id",
                            "currency_id",
                        ),
                        key,
                        strict=True,
                    )
                ),
                "scenario_a": format(a, "f"),
                "scenario_b": format(b, "f"),
                "delta": format(b - a, "f"),
            }
        )
    return {
        "contract": "planning-comparison/1",
        "scenario_a": scenarios[str(scenario_a)],
        "scenario_b": scenarios[str(scenario_b)],
        "rows": rows,
        "coverage": "ACCEPTED_PLANNING_CELL_FACTS",
        "forecast_calculation_available": False,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }

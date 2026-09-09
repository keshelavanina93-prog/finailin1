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
        bucket[str(attrs["scenario_version_id"])] = (
            bucket.get(str(attrs["scenario_version_id"]), Decimal(0)) + amount
        )
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


def forecast(principal, scenario_id: UUID) -> dict[str, Any]:
    """Project accepted scenario cells into a deterministic period forecast.

    This is a governed arithmetic projection, not model inference. It never
    creates facts, changes the ledger, or promotes a planning scenario.
    """
    require_permission(principal, "ontology_read")
    company_id = str(principal.scope.legal_entity_id)
    scenarios = {
        str(row["resource_id"]): row
        for row in _resources(principal, "ScenarioVersion")
        if not row["attributes"].get("legal_entity_id")
        or str(row["attributes"].get("legal_entity_id")) == company_id
    }
    selected = scenarios.get(str(scenario_id))
    if selected is None:
        raise WorkspaceError(404, "Scenario is unavailable in the authorized company scope")
    kind = str(selected["attributes"].get("kind", "")).upper()
    if kind not in {"PLAN", "FORECAST"}:
        raise WorkspaceError(409, "Forecast projection requires a PLAN or FORECAST scenario")
    buckets: dict[tuple[str, ...], Decimal] = {}
    for row in _resources(principal, "PlanningCellFact"):
        attrs = row["attributes"]
        if str(attrs.get("legal_entity_id")) != company_id or str(
            attrs.get("scenario_version_id")
        ) != str(scenario_id):
            continue
        try:
            amount = Decimal(str(attrs["amount"]))
        except (InvalidOperation, KeyError) as exc:
            raise WorkspaceError(409, "Accepted planning cell contains an invalid amount") from exc
        key = tuple(str(attrs.get(name, "")) for name in ("period_id", "measure", "currency_id"))
        buckets[key] = buckets.get(key, Decimal(0)) + amount
    rows = [
        {
            "period_id": key[0],
            "measure": key[1],
            "currency_id": key[2],
            "amount": format(value, "f"),
        }
        for key, value in sorted(buckets.items())
    ]
    return {
        "contract": "forecast-projection/1",
        "scenario": selected,
        "rows": rows,
        "coverage": "ACCEPTED_PLANNING_CELL_FACTS",
        "calculation": "DETERMINISTIC_DECIMAL_AGGREGATION",
        "model_backed": False,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def liquidity(principal, scenario_id: UUID) -> dict[str, Any]:
    """Build a currency-partitioned cash projection from accepted planning facts."""
    require_permission(principal, "ontology_read")
    company_id = str(principal.scope.legal_entity_id)
    scenarios = {
        str(row["resource_id"]): row
        for row in _resources(principal, "ScenarioVersion")
        if not row["attributes"].get("legal_entity_id")
        or str(row["attributes"].get("legal_entity_id")) == company_id
    }
    selected = scenarios.get(str(scenario_id))
    if selected is None:
        raise WorkspaceError(404, "Scenario is unavailable in the authorized company scope")
    buckets: dict[tuple[str, str], dict[str, Decimal]] = {}
    for row in _resources(principal, "PlanningCellFact"):
        attrs = row["attributes"]
        if str(attrs.get("legal_entity_id")) != company_id or str(
            attrs.get("scenario_version_id")
        ) != str(scenario_id):
            continue
        if str(attrs.get("measure", "")).lower() not in {"cash", "cash_flow", "liquidity"}:
            continue
        try:
            amount = Decimal(str(attrs["amount"]))
        except (InvalidOperation, KeyError) as exc:
            raise WorkspaceError(409, "Accepted liquidity cell contains an invalid amount") from exc
        direction = str(attrs.get("direction", attrs.get("cash_flow_direction", "NET"))).upper()
        signed = (
            -abs(amount)
            if direction in {"OUTFLOW", "OUT", "PAYMENT"}
            else abs(amount)
            if direction in {"INFLOW", "IN"}
            else amount
        )
        bucket = buckets.setdefault(
            (str(attrs.get("period_id", "")), str(attrs.get("currency_id", ""))),
            {"inflow": Decimal(0), "outflow": Decimal(0), "net": Decimal(0)},
        )
        bucket["inflow"] += signed if signed > 0 else Decimal(0)
        bucket["outflow"] += abs(signed) if signed < 0 else Decimal(0)
        bucket["net"] += signed
    rows = [
        {
            "period_id": key[0],
            "currency_id": key[1],
            **{name: format(value, "f") for name, value in values.items()},
        }
        for key, values in sorted(buckets.items())
    ]
    return {
        "contract": "liquidity-projection/1",
        "scenario": selected,
        "rows": rows,
        "coverage": "ACCEPTED_CASH_PLANNING_CELL_FACTS",
        "calculation": "DETERMINISTIC_SIGNED_DECIMAL_AGGREGATION",
        "treasury_authority": False,
        "business_effect_authorized": False,
    }

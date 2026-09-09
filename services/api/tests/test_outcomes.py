from uuid import UUID

import pytest

from finai_api.services import outcomes
from finai_api.services.workspace import WorkspaceError


def _principal():
    return type(
        "P",
        (),
        {
            "scope": type(
                "S", (), {"legal_entity_id": UUID("00000000-0000-0000-0000-000000000001")}
            )(),
            "permissions": ["ontology_read"],
        },
    )()


def test_actual_vs_plan_requires_actual_kind(monkeypatch):
    principal = _principal()
    plan = UUID("10000000-0000-0000-0000-000000000001")
    actual = UUID("20000000-0000-0000-0000-000000000001")
    rows = [
        {
            "resource_id": plan,
            "attributes": {"legal_entity_id": str(principal.scope.legal_entity_id), "kind": "PLAN"},
        },
        {
            "resource_id": actual,
            "attributes": {
                "legal_entity_id": str(principal.scope.legal_entity_id),
                "kind": "FORECAST",
            },
        },
    ]
    monkeypatch.setattr(
        outcomes.planning, "_resources", lambda _p, kind: rows if kind == "ScenarioVersion" else []
    )
    with pytest.raises(WorkspaceError, match="ACTUAL"):
        outcomes.actual_vs_plan(principal, plan, actual)


def test_actual_vs_plan_returns_decimal_variance(monkeypatch):
    principal = _principal()
    plan = UUID("10000000-0000-0000-0000-000000000001")
    actual = UUID("20000000-0000-0000-0000-000000000001")
    base = {
        "legal_entity_id": str(principal.scope.legal_entity_id),
        "period_id": "2025-01",
        "measure": "amount",
    }
    scenarios = [
        {"resource_id": plan, "attributes": {**base, "kind": "PLAN"}},
        {"resource_id": actual, "attributes": {**base, "kind": "ACTUAL"}},
    ]
    cells = [
        {
            "resource_id": "p",
            "attributes": {**base, "scenario_version_id": str(plan), "amount": "10.10"},
        },
        {
            "resource_id": "a",
            "attributes": {**base, "scenario_version_id": str(actual), "amount": "12.35"},
        },
    ]
    monkeypatch.setattr(
        outcomes.planning,
        "_resources",
        lambda _p, kind: scenarios if kind == "ScenarioVersion" else cells,
    )
    result = outcomes.actual_vs_plan(principal, plan, actual)
    assert result["contract"] == "outcome-measurement/1"
    assert result["rows"][0]["variance"] == "2.25"
    assert result["learning_candidate_created"] is False

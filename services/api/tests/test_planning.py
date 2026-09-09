from types import SimpleNamespace
from uuid import UUID, uuid4

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services import planning


def principal() -> Principal:
    return Principal(
        actor_id="planner",
        display_name="Planner",
        scope=ExactScope(
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            legal_entity_id="company-a",
            period="2025-01",
            currency="GEL",
        ),
        permissions=("read", "ontology_read"),
    )


def node(resource_id, object_type, attributes):
    return SimpleNamespace(
        model_dump=lambda mode=None: {
            "resource_id": str(resource_id),
            "version_id": str(uuid4()),
            "object_type": object_type,
            "attributes": attributes,
            "authority_state": "APPROVED",
        }
    )


def test_compare_is_exact_scope_and_decimal_deterministic(monkeypatch):
    scenario_a, scenario_b = uuid4(), uuid4()
    rows = {
        "ScenarioVersion": [
            node(scenario_a, "ScenarioVersion", {"code": "BUDGET", "kind": "BUDGET"}),
            node(scenario_b, "ScenarioVersion", {"code": "FCST", "kind": "FORECAST"}),
        ],
        "PlanningCellFact": [
            node(
                uuid4(),
                "PlanningCellFact",
                {
                    "budget_article_id": "fuel",
                    "legal_entity_id": "company-a",
                    "period_id": "2025-01",
                    "department_id": "retail",
                    "measure": "GEL",
                    "currency_id": "gel",
                    "scenario_version_id": str(scenario_a),
                    "amount": "100.10",
                },
            ),
            node(
                uuid4(),
                "PlanningCellFact",
                {
                    "budget_article_id": "fuel",
                    "legal_entity_id": "company-a",
                    "period_id": "2025-01",
                    "department_id": "retail",
                    "measure": "GEL",
                    "currency_id": "gel",
                    "scenario_version_id": str(scenario_b),
                    "amount": "125.25",
                },
            ),
            node(
                uuid4(),
                "PlanningCellFact",
                {
                    "budget_article_id": "fuel",
                    "legal_entity_id": "company-b",
                    "period_id": "2025-01",
                    "department_id": "retail",
                    "measure": "GEL",
                    "currency_id": "gel",
                    "scenario_version_id": str(scenario_b),
                    "amount": "999.99",
                },
            ),
        ],
    }
    monkeypatch.setattr(
        planning.resources,
        "list_resources",
        lambda _principal, object_type, _search, _offset, **_kwargs: rows[object_type],
    )

    result = planning.compare(principal(), scenario_a, scenario_b)

    assert result["contract"] == "planning-comparison/1"
    assert result["rows"][0]["scenario_a"] == "100.10"
    assert result["rows"][0]["scenario_b"] == "125.25"
    assert result["rows"][0]["delta"] == "25.15"

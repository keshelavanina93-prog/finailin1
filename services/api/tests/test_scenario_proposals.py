from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from finai_api.api.planning_routes import (
    ScenarioCellInput,
    ScenarioProposalRequest,
    propose_scenario,
)
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal


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
        permissions=("read", "ontology_read", "ontology_propose"),
    )


def test_scenario_proposal_builds_reviewable_scenario_and_cells(monkeypatch):
    captured = {}

    def retain(_principal, proposal):
        captured["proposal"] = proposal
        return SimpleNamespace(
            model_dump=lambda mode=None: {"proposal_id": str(proposal.proposal_id)}
        )

    monkeypatch.setattr("finai_api.api.planning_routes.resources.propose", retain)
    request = ScenarioProposalRequest(
        code="Q4-FCST",
        kind="FORECAST",
        valid_from=datetime(2025, 10, 1, tzinfo=UTC),
        rationale="Create a reviewed forecast scenario for Q4 planning analysis.",
        cells=[
            ScenarioCellInput(
                budget_article_id="fuel",
                period_id="2025-10",
                period_starts_on="2025-10-01",
                period_ends_on="2025-10-31",
                department_id="retail",
                measure="GEL",
                source_family="MANUAL_PLANNING",
                amount="125.25",
                currency_id="GEL",
                scale=2,
            )
        ],
    )
    result = propose_scenario(principal(), request)
    proposal = captured["proposal"]
    assert result["contract"] == "scenario-proposal/1"
    assert result["review_required"] is True
    assert [item.object_type for item in proposal.mutations] == [
        "ScenarioVersion",
        "PlanningCellFact",
    ]
    assert proposal.mutations[0].attributes["kind"] == "FORECAST"
    assert proposal.mutations[1].attributes["scenario_version_id"] == result["scenario_id"]

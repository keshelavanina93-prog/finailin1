import pytest
from pydantic import ValidationError

from finai_api.domain.workspace_projections import (
    WorkspaceSelection,
    eligible_projections,
    normalize_projection_rows,
    projection_catalog,
    replay_timestamp,
)


def test_projection_catalog_is_server_owned_and_read_only() -> None:
    catalog = projection_catalog()
    assert {item["projection_id"] for item in catalog} >= {
        "operations-map",
        "movement-network",
        "variance-waterfall",
        "evidence-table",
        "nyx-context",
    }
    assert {item["kind"] for item in catalog} >= {
        "ACTION", "CHART", "FIELD", "GRID", "HIERARCHY", "IMAGE", "KPI",
        "MAP", "NETWORK", "TABLE", "TEXT", "WATERFALL",
    }
    assert {item["chart_type"] for item in catalog if item["chart_type"]} >= {
        "AREA", "BAR", "COLUMN", "COMBINATION", "DOT", "GANTT", "LINE",
        "PIE", "SCATTER", "BUBBLE", "WATERFALL",
    }
    assert all(item["authority_effect"] == "NONE" for item in catalog)
    assert all(item["synchronization_group"] == "WORKSPACE_SELECTION" for item in catalog)


def test_selection_preserves_exact_cross_projection_dimensions() -> None:
    selection = WorkspaceSelection(
        company_id="sgp",
        product_id="diesel-en590",
        station_id="024",
        period="2026-09",
        scenario_id="forecast-v3",
        version_id="v3",
        comparison_baseline="budget-2026",
        replay_as_of="2026-09-10T12:00:00Z",
    )
    assert selection.model_dump()["company_id"] == "sgp"
    assert selection.model_dump()["replay_as_of"] == "2026-09-10T12:00:00Z"


def test_selection_rejects_empty_company_scope() -> None:
    with pytest.raises(ValidationError):
        WorkspaceSelection(company_id="")


def test_projection_eligibility_does_not_invent_missing_context() -> None:
    selection = WorkspaceSelection(company_id="sgp", workspace="BRIDGE_FIRST")
    eligible = {item["projection_id"] for item in eligible_projections(selection)}
    assert "variance-waterfall" not in eligible
    assert "executive-kpi" not in eligible
    assert "action-control" not in eligible


def test_replay_timestamp_is_parsed_for_bitemporal_projection_reads() -> None:
    selection = WorkspaceSelection(company_id="company", replay_as_of="2026-09-10T08:30:00Z")
    parsed = replay_timestamp(selection)
    assert parsed is not None
    assert parsed.isoformat() == "2026-09-10T08:30:00+00:00"


def test_invalid_replay_timestamp_is_refused() -> None:
    selection = WorkspaceSelection(company_id="company", replay_as_of="not-a-time")
    with pytest.raises(ValueError, match="ISO-8601"):
        replay_timestamp(selection)


def test_projection_rows_expose_typed_coordinate_measure_and_evidence_envelope() -> None:
    rows = normalize_projection_rows([{
        "resource_id": "row-1",
        "dimension": {"company_id": "sgp", "period": "2026-09"},
        "amount": "12.50",
        "authority_state": "APPROVED_CANONICAL",
        "evidence_id": "evidence-1",
    }])
    assert rows[0].coordinates == {"company_id": "sgp", "period": "2026-09"}
    assert rows[0].measures == {"amount": "12.50"}
    assert rows[0].evidence_refs == ("evidence-1", "row-1")

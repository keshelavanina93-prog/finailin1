import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from finai_api.domain.workspace_projections import (
    WorkspaceSelection,
    eligible_projections,
    normalize_projection_rows,
    projection_catalog,
    replay_timestamp,
)
from finai_api.main import app


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
    statuses = {item["projection_id"]: item["status"] for item in catalog}
    assert statuses["variance-waterfall"] == "IMPLEMENTED"
    assert statuses["formatted-table"] == "IMPLEMENTED"
    assert statuses["chart-bubble"] == "IMPLEMENTED"
    assert statuses["field-input"] == "PARTIAL"
    assert statuses["action-control"] == "PARTIAL"
    assert statuses["image-evidence"] == "IMPLEMENTED"


def test_selection_preserves_exact_cross_projection_dimensions() -> None:
    selection = WorkspaceSelection(
        company_id="sgp",
        facility_id="tbilisi-depot",
        tank_id="T-04",
        product_id="diesel-en590",
        station_id="024",
        period="2026-09",
        scenario_id="forecast-v3",
        version_id="v3",
        comparison_baseline="budget-2026",
        replay_as_of="2026-09-10T12:00:00Z",
    )
    assert selection.model_dump()["company_id"] == "sgp"
    assert selection.model_dump()["facility_id"] == "tbilisi-depot"
    assert selection.model_dump()["tank_id"] == "T-04"
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


def test_field_projection_returns_exact_selection_context_without_mutation() -> None:
    selection = WorkspaceSelection(
        company_id="sgp",
        facility_id="tbilisi-depot",
        tank_id="T-04",
        product_id="diesel-en590",
        period="2026-09",
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/projections/data",
            json={"projection_id": "field-input", "selection": selection.model_dump()},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == "workspace-selection/1"
    assert body["authority_effect"] == "NONE"
    assert {row["field"] for row in body["rows"]} >= {
        "company_id", "facility_id", "tank_id", "product_id", "period"
    }


def test_action_projection_exposes_boundary_without_execution() -> None:
    selection = WorkspaceSelection(company_id="sgp", selected_object_id="workflow-1")
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/projections/data",
            json={"projection_id": "action-control", "selection": selection.model_dump()},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data_state"] == "CONTEXT_ONLY"
    assert body["authority_effect"] == "NONE"
    values = {row["field"]: row["value"] for row in body["rows"]}
    assert values["approval_state"] == "APPROVAL_REQUIRED"
    assert values["execution"] == "NOT_PERMITTED_FROM_PROJECTION"


def test_nyx_projection_refuses_without_valid_exact_resource_ids() -> None:
    selection = WorkspaceSelection(
        company_id="sgp",
        selected_object_id="not-a-resource-id",
        period="2026-09",
        scenario_id="actual",
        version_id="not-a-version-id",
        replay_as_of="2026-09-10T12:00:00Z",
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/projections/data",
            json={"projection_id": "nyx-context", "selection": selection.model_dump()},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data_state"] == "UNAVAILABLE_REQUIRED_CONTEXT"
    assert body["authority_effect"] == "NONE"
    assert body["rows"] == []


def test_projection_rows_expose_typed_coordinate_measure_and_evidence_envelope() -> None:
    rows = normalize_projection_rows([{
        "resource_id": "row-1",
        "dimension": {"company_id": "sgp", "period": "2026-09"},
        "amount": "12.50",
        "authority_state": "APPROVED_CANONICAL",
        "evidence_id": "evidence-1",
        "period_starts_on": "2026-09-01",
        "period_ends_on": "2026-09-30",
    }])
    assert rows[0].coordinates == {"company_id": "sgp", "period": "2026-09"}
    assert rows[0].measures == {"amount": "12.50"}
    assert rows[0].evidence_refs == ("evidence-1", "row-1")
    assert rows[0].interval_start == "2026-09-01"
    assert rows[0].interval_end == "2026-09-30"

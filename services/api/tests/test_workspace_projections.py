from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from finai_api.api import enterprise_diagnostics_routes
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


def test_projection_catalog_covers_every_declared_card_and_chart_variant() -> None:
    catalog = projection_catalog()
    projection_ids = {item["projection_id"] for item in catalog}
    assert projection_ids >= {
        "executive-kpi", "planning-grid", "formatted-table", "variance-waterfall",
        "hierarchy-drilldown", "movement-network", "operations-map", "evidence-table",
        "nyx-context", "field-input", "image-evidence", "action-control",
        "chart-area", "chart-bar", "chart-column", "chart-combination", "chart-dot",
        "chart-gantt", "chart-line", "chart-pie", "chart-scatter", "chart-bubble",
    }
    assert {item["kind"] for item in catalog} == {
        "ACTION", "CHART", "FIELD", "GRID", "HIERARCHY", "IMAGE", "KPI",
        "MAP", "NETWORK", "TABLE", "TEXT", "WATERFALL",
    }
    assert {item["chart_type"] for item in catalog if item["chart_type"]} == {
        "AREA", "BAR", "COLUMN", "COMBINATION", "DOT", "GANTT", "LINE",
        "PIE", "SCATTER", "BUBBLE", "WATERFALL",
    }


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


def test_selection_endpoint_round_trips_full_context_for_synchronization() -> None:
    selection = WorkspaceSelection(
        selected_object_id="variance-1",
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
        workspace="REPORT",
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/projections/selection", json=selection.model_dump()
        )
    assert response.status_code == 200
    body = response.json()
    assert body["contract"] == "workspace-selection/1"
    assert body["authority_effect"] == "NONE"
    assert body["selection"] == selection.model_dump()
    eligible_ids = {item["projection_id"] for item in body["eligible_projections"]}
    assert {"formatted-table", "chart-line", "image-evidence"} <= eligible_ids


def test_every_registered_projection_has_a_typed_read_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog must not contain a card family with no API dispatch branch."""

    company_id = "11111111-1111-4111-8111-111111111111"
    selected_id = "22222222-2222-4222-8222-222222222222"
    scenario_id = "33333333-3333-4333-8333-333333333333"
    baseline_id = "44444444-4444-4444-8444-444444444444"
    version_id = "55555555-5555-4555-8555-555555555555"
    monkeypatch.setattr(
        enterprise_diagnostics_routes.planning,
        "catalog",
        lambda *_args: {"cells": [{
            "row_id": "planning:1",
            "label": "Revenue",
            "amount": "100.00",
            "period_id": "2026-09",
            "attributes": {"scenario_version_id": scenario_id},
        }]},
    )
    monkeypatch.setattr(
        enterprise_diagnostics_routes.planning,
        "compare",
        lambda *_args: {
            "rows": [{
                "row_id": "comparison:1",
                "label": "Revenue variance",
                "delta": "10.00",
                "scenario_a": "100.00",
                "scenario_b": "90.00",
            }],
            "coverage": "planning-comparison/1",
        },
    )
    monkeypatch.setattr(
        enterprise_diagnostics_routes.operations_map,
        "map_view",
        lambda *_args, **_kwargs: {"features": [], "contract": "operations-map/1"},
    )
    monkeypatch.setattr(
        enterprise_diagnostics_routes.operations_map,
        "connections",
        lambda *_args, **_kwargs: {"edges": [], "contract": "operations-connections/1"},
    )
    monkeypatch.setattr(
        enterprise_diagnostics_routes.nyx_reasoning,
        "reason",
        lambda *_args, **_kwargs: {
            "answer": "The selected evidence is retained and read-only.",
            "state": "EXPLANATION",
            "contract": "nyx-reason/1",
        },
    )
    monkeypatch.setattr(
        enterprise_diagnostics_routes.operator_workbench,
        "listing",
        lambda *_args, **_kwargs: {"items": [], "truncated": False},
    )
    selection = WorkspaceSelection(
        selected_object_id=selected_id,
        company_id=company_id,
        facility_id="tbilisi-depot",
        tank_id="T-04",
        product_id="diesel-en590",
        station_id="024",
        period="2026-09",
        scenario_id=scenario_id,
        version_id=version_id,
        comparison_baseline=baseline_id,
        replay_as_of="2026-09-10T12:00:00Z",
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        catalog = client.get("/v1/workspace/projections/catalog").json()
        response_by_id = {}
        for definition in catalog["projections"]:
            response = client.post(
                "/v1/workspace/projections/data",
                json={
                    "projection_id": definition["projection_id"],
                    "selection": selection.model_dump(),
                },
            )
            assert response.status_code == 200, definition["projection_id"]
            body = response.json()
            assert body["contract"] == "workspace-projection-data/1"
            assert body["projection"]["projection_id"] == definition["projection_id"]
            assert body["authority_effect"] == "NONE"
            response_by_id[definition["projection_id"]] = body
    assert set(response_by_id) == {item["projection_id"] for item in catalog["projections"]}
    assert response_by_id["nyx-context"]["data_state"] == "CONTEXT_ONLY"
    assert response_by_id["image-evidence"]["data_state"] == "UNAVAILABLE_REQUIRED_CONTEXT"
    assert response_by_id["action-control"]["data_state"] == "CONTEXT_ONLY"


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


def test_action_projection_reads_exact_company_workbench_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(
        enterprise_diagnostics_routes.operator_workbench,
        "listing",
        lambda _principal, _company_id, include_unbound: {
            "items": [
                {
                    "workflow_id": "workflow-1",
                    "title": "Review retained source exception",
                    "family": "source",
                    "company_id": company_id,
                    "created_at": "2026-09-10T12:00:00+00:00",
                }
            ],
            "truncated": False,
        },
    )
    selection = WorkspaceSelection(company_id=company_id)
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/projections/data",
            json={"projection_id": "action-control", "selection": selection.model_dump()},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data_state"] == "ACCEPTED_CANONICAL"
    assert body["coverage"] == "workflow/workbench/1"
    assert any(row.get("workflow_id") == "workflow-1" for row in body["rows"])
    values = {row["field"]: row["value"] for row in body["rows"] if "value" in row}
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


def test_image_projection_returns_hash_bound_retained_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"\x89PNG\r\n\x1a\nretained-image"
    monkeypatch.setattr(
        enterprise_diagnostics_routes.accounting_source_document,
        "read_source",
        lambda _principal, _identity: (
            {"filename": "tank-dip.png", "source_sha256": sha256(content).hexdigest()},
            content,
        ),
    )
    selection = WorkspaceSelection(
        company_id="sgp",
        selected_object_id="doc_" + "a" * 64,
        replay_as_of="2026-09-10T12:00:00Z",
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/projections/data",
            json={"projection_id": "image-evidence", "selection": selection.model_dump()},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["data_state"] == "ACCEPTED_CANONICAL"
    assert body["coverage"] == "retained-image/1"
    assert body["media"]["media_type"] == "image/png"
    assert body["media"]["data_url"].startswith("data:image/png;base64,")
    assert body["media"]["sha256"] == sha256(content).hexdigest()


def test_image_projection_refuses_non_image_retained_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enterprise_diagnostics_routes.accounting_source_document,
        "read_source",
        lambda _principal, _identity: (
            {"filename": "source.xls", "source_sha256": "a" * 64},
            b"not-an-image",
        ),
    )
    selection = WorkspaceSelection(
        company_id="sgp",
        selected_object_id="doc_" + "b" * 64,
        replay_as_of="2026-09-10T12:00:00Z",
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/v1/workspace/projections/data",
            json={"projection_id": "image-evidence", "selection": selection.model_dump()},
        )
    assert response.status_code == 200
    assert response.json()["data_state"] == "UNAVAILABLE_AUTHORITY_PAYLOAD"


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

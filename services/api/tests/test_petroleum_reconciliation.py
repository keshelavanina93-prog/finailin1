from datetime import UTC, datetime
from uuid import UUID

from finai_api.services import petroleum_control, petroleum_reconciliation


class FakeResource:
    def __init__(self, resource_id, attributes):
        self.resource_id = resource_id
        self.attributes = attributes

    def model_dump(self, mode="json"):
        return {"resource_id": str(self.resource_id), "attributes": self.attributes}


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


def test_reconcile_preserves_conservation_and_financial_boundary(monkeypatch):
    rows = {
        "InventoryBalance": [
            FakeResource(
                UUID("30000000-0000-0000-0000-000000000001"),
                {
                    "legal_entity_id": "00000000-0000-0000-0000-000000000001",
                    "facility_id": "f",
                    "tank_id": "t",
                    "product_id": "diesel",
                    "period_id": "2025-01",
                    "unit": "L",
                    "opening_quantity": "100",
                    "receipts": "50",
                    "dispatches": "20",
                    "losses": "5",
                    "closing_quantity": "125",
                },
            )
        ],
        "PhysicalMovement": [],
        "PhysicalMeasurement": [],
        "RetailSale": [],
    }
    monkeypatch.setattr(
        petroleum_reconciliation.resources,
        "list_resources",
        lambda _p, kind, _s, _o, limit=1000: rows[kind],
    )
    result = petroleum_reconciliation.reconcile(_principal())
    assert result["contract"] == "petroleum-reconciliation/1"
    assert result["rows"][0]["variance"] == "0"
    assert result["rows"][0]["status"] == "RECONCILED"
    assert result["accounting_authorized"] is False
    assert result["business_effect_authorized"] is False


def test_variance_is_full_scope_bitemporal_and_partial_bridge(monkeypatch):
    entity = str(_principal().scope.legal_entity_id)
    rows = {
        "InventoryBalance": [FakeResource(UUID("30000000-0000-0000-0000-000000000009"), {
            "legal_entity_id": entity, "facility_id": "depot-1", "tank_id": "T-04",
            "station_id": "024", "product_id": "diesel", "period_id": "2025-04",
            "unit": "L", "measurement_basis": "15C", "opening_quantity": "100",
            "receipts": "20", "dispatches": "18", "losses": "1", "closing_quantity": "99",
            "waybill_id": "wb-1", "tank_dip_id": "dip-1", "source_sha256": "a" * 64,
        })], "PhysicalMovement": [], "PhysicalMeasurement": [], "RetailSale": [],
    }
    monkeypatch.setattr(petroleum_reconciliation.resources, "list_resources",
                        lambda _p, kind, _s, _o, limit=1000: rows[kind])
    result = petroleum_reconciliation.variances(_principal(), known_at=None)
    row = result["rows"][0]
    assert row["contract"] == "petroleum-variance/1"
    assert row["dimensions"]["tank_id"] == "T-04"
    assert row["physical"]["variance_quantity"] == "-2"
    assert row["financial"]["status"] == "FINANCIAL_BRIDGE_PARTIAL"
    assert row["authority"]["accounting_authorized"] is False
    assert row["evidence"]["waybill_ids"] == ["wb-1"]
    assert row["evidence"]["tank_dip_ids"] == ["dip-1"]
    assert row["evidence"]["source_hashes"] == ["a" * 64]
    assert row["time"]["replay_as_of"] is None


def test_variance_detail_returns_evidence_packet_and_lineage(monkeypatch):
    principal = _principal()
    entity = str(principal.scope.legal_entity_id)
    rows = {
        "InventoryBalance": [FakeResource(UUID("30000000-0000-0000-0000-000000000011"), {
            "legal_entity_id": entity, "facility_id": "depot-1", "tank_id": "T-04",
            "product_id": "diesel", "period_id": "2025-04", "unit": "L",
            "opening_quantity": "100", "receipts": "20", "dispatches": "18",
            "losses": "1", "closing_quantity": "99", "source_sha256": "b" * 64,
            "tank_dip_id": "dip-1",
        })], "PhysicalMovement": [], "PhysicalMeasurement": [], "RetailSale": [],
        "ProductCost": [],
    }
    monkeypatch.setattr(petroleum_reconciliation.resources, "list_resources",
                        lambda _p, kind, _s, _o, limit=1000: rows.get(kind, []))
    monkeypatch.setattr(
        petroleum_reconciliation,
        "lineage",
        lambda _p, resource_id, _company_id=None: {"root_resource_id": str(resource_id)},
    )
    variance = petroleum_reconciliation.variances(principal)["rows"][0]
    detail = petroleum_reconciliation.variance_detail(principal, variance["variance_id"])
    assert detail["contract"] == "petroleum-variance-detail/1"
    assert detail["evidence_packet"]["tank_dip_ids"] == ["dip-1"]
    assert detail["evidence_packet"]["source_hashes"] == ["b" * 64]
    assert detail["accounting_effect"] == "NOT_YET_AUTHORITATIVE"
    assert detail["lineage"]


def test_reconcile_replay_excludes_evidence_known_after_cutoff(monkeypatch):
    entity = str(_principal().scope.legal_entity_id)
    rows = {
        "InventoryBalance": [
            FakeResource(UUID("30000000-0000-0000-0000-000000000010"), {
                "legal_entity_id": entity, "facility_id": "depot-1", "tank_id": "T-04",
                "product_id": "diesel", "period_id": "2025-04", "unit": "L",
                "opening_quantity": "100", "closing_quantity": "100",
                "known_at": "2025-05-01T00:00:00+00:00",
            })
        ], "PhysicalMovement": [], "PhysicalMeasurement": [], "RetailSale": [],
    }
    monkeypatch.setattr(petroleum_reconciliation.resources, "list_resources",
                        lambda _p, kind, _s, _o, limit=1000: rows[kind])
    result = petroleum_reconciliation.reconcile(
        _principal(), known_at=datetime(2025, 4, 30, tzinfo=UTC)
    )
    assert result["rows"] == []


def test_petroleum_control_requires_independent_checker(monkeypatch):
    principal = _principal()
    principal.actor_id = "maker"
    principal.permissions = ["ontology_read", "ontology_review"]
    monkeypatch.setattr(petroleum_control, "read", lambda _p, _id: {
        "state": "ACTION_PROPOSED", "initiator_actor_id": "maker"
    })
    try:
        petroleum_control.decide(
            principal, "pvc_test",
            petroleum_control.ControlDecisionRequest(
                decision="APPROVE_ACTION", rationale="Independent approval is required"
            ),
        )
    except Exception as exc:
        assert "independent reviewer" in str(exc)
    else:
        raise AssertionError("maker must not approve its own petroleum action")


def test_petroleum_control_finds_variance_for_named_legal_entity(monkeypatch):
    principal = _principal()
    principal.scope.legal_entity_id = "SOCAR_PETROLEUM_GEORGIA"
    target = {"variance_id": "petroleum-variance:named-company"}
    calls = []

    def variances(actor):
        calls.append(actor)
        return {"rows": [target]}

    monkeypatch.setattr(petroleum_control.petroleum_reconciliation, "variances", variances)

    assert petroleum_control._find(principal, target["variance_id"]) == target
    assert calls == [principal]


def test_variance_valuation_is_candidate_only_when_product_cost_is_accepted(monkeypatch):
    entity = str(_principal().scope.legal_entity_id)
    rows = {
        "InventoryBalance": [FakeResource(UUID("30000000-0000-0000-0000-000000000011"), {
            "legal_entity_id": entity, "facility_id": "depot-1", "tank_id": "T-04",
            "product_id": "diesel", "period_id": "2025-04", "unit": "L",
            "opening_quantity": "100", "receipts": "0", "dispatches": "0",
            "losses": "0", "closing_quantity": "90",
        })], "PhysicalMovement": [], "PhysicalMeasurement": [], "RetailSale": [],
        "ProductCost": [FakeResource(UUID("60000000-0000-0000-0000-000000000011"), {
            "legal_entity_id": entity, "facility_id": "depot-1", "tank_id": "T-04",
            "product_id": "diesel", "period_id": "2025-04", "unit": "L",
            "unit_cost": "3.5", "valuation_basis": "WEIGHTED_AVERAGE",
        })],
    }
    monkeypatch.setattr(petroleum_reconciliation.resources, "list_resources",
                        lambda _p, kind, _s, _o, limit=1000: rows[kind])
    row = petroleum_reconciliation.variances(_principal())["rows"][0]
    assert row["financial"]["status"] == "FINANCIAL_BRIDGED"
    assert row["financial"]["estimated_value"] == "35.0"
    assert row["authority"]["accounting_authorized"] is False


def test_lineage_returns_only_referenced_accepted_resources(monkeypatch):
    root = UUID("30000000-0000-0000-0000-000000000001")
    child = UUID("40000000-0000-0000-0000-000000000001")
    rows = {
        "InventoryBalance": [],
        "PhysicalMovement": [
            FakeResource(
                root,
                {
                    "legal_entity_id": str(_principal().scope.legal_entity_id),
                    "destination_id": str(child),
                },
            ),
        ],
        "PhysicalMeasurement": [
            FakeResource(
                child,
                {"legal_entity_id": str(_principal().scope.legal_entity_id)},
            ),
        ],
        "RetailSale": [],
    }
    monkeypatch.setattr(
        petroleum_reconciliation.resources,
        "list_resources",
        lambda _p, kind, _s, _o, limit=1000: rows[kind],
    )
    result = petroleum_reconciliation.lineage(_principal(), root)
    assert result["contract"] == "petroleum-lineage/1"
    assert len(result["resources"]) == 2
    assert result["edges"][0]["field"] == "destination_id"


def test_margin_bridge_keeps_revenue_volume_and_cogs_dimensionally_separate(monkeypatch):
    rows = {
        "RetailSale": [
            FakeResource(
                UUID("50000000-0000-0000-0000-000000000001"),
                {
                    "legal_entity_id": str(_principal().scope.legal_entity_id),
                    "station_id": "station-1",
                    "product_id": "diesel",
                    "period_id": "2025-01",
                    "currency": "GEL",
                    "quantity": "100",
                    "net_amount": "350",
                },
            )
        ],
        "ProductCost": [
            FakeResource(
                UUID("60000000-0000-0000-0000-000000000001"),
                {
                    "legal_entity_id": str(_principal().scope.legal_entity_id),
                    "station_id": "station-1",
                    "product_id": "diesel",
                    "period_id": "2025-01",
                    "currency": "GEL",
                    "cost_amount": "280",
                },
            )
        ],
    }
    monkeypatch.setattr(
        petroleum_reconciliation.resources,
        "list_resources",
        lambda _p, kind, _s, _o, limit=1000: rows[kind],
    )
    result = petroleum_reconciliation.margin(_principal())
    row = result["rows"][0]
    assert row["volume"] == "100"
    assert row["revenue"] == "350"
    assert row["cogs"] == "280"
    assert row["gross_margin"] == "70"
    assert row["status"] == "COMPLETE"
    assert result["accounting_authorized"] is False


def test_movement_journal_reconciliation_reports_reference_and_quantity_state(monkeypatch):
    movement_id = UUID("70000000-0000-0000-0000-000000000001")
    line_id = UUID("80000000-0000-0000-0000-000000000001")
    rows = {
        "PhysicalMovement": [
            FakeResource(
                movement_id,
                {
                    "legal_entity_id": str(_principal().scope.legal_entity_id),
                    "movement_id": "move-1",
                    "document_id": "doc-1",
                    "product_id": "diesel",
                    "unit": "L",
                    "period_id": "2025-01",
                    "quantity": "100",
                },
            ),
        ],
        "JournalLine": [
            FakeResource(
                line_id,
                {
                    "legal_entity_id": str(_principal().scope.legal_entity_id),
                    "source_document_id": "doc-1",
                    "quantity": "100",
                },
            ),
        ],
    }
    monkeypatch.setattr(
        petroleum_reconciliation.resources,
        "list_resources",
        lambda _p, kind, _s, _o, limit=1000: rows[kind],
    )
    result = petroleum_reconciliation.movement_journal_reconciliation(_principal())
    assert result["contract"] == "movement-journal-reconciliation/1"
    assert result["rows"][0]["status"] == "MATCHED"
    assert result["rows"][0]["journal_line_resource_id"] == str(line_id)
    assert result["accounting_authorized"] is False


def test_movement_journal_reconciliation_exposes_missing_journal(monkeypatch):
    rows = {
        "PhysicalMovement": [
            FakeResource(
                UUID("70000000-0000-0000-0000-000000000002"),
                {
                    "legal_entity_id": str(_principal().scope.legal_entity_id),
                    "movement_id": "move-2",
                    "quantity": "10",
                    "unit": "L",
                },
            )
        ],
        "JournalLine": [],
    }
    monkeypatch.setattr(
        petroleum_reconciliation.resources,
        "list_resources",
        lambda _p, kind, _s, _o, limit=1000: rows[kind],
    )
    result = petroleum_reconciliation.movement_journal_reconciliation(_principal())
    assert result["rows"][0]["status"] == "MISSING_JOURNAL"


def test_telemetry_bridge_reports_basis_and_series_gaps(monkeypatch):
    entity = str(_principal().scope.legal_entity_id)
    rows = {
        "PhysicalMeasurement": [
            FakeResource(
                UUID("90000000-0000-0000-0000-000000000001"),
                {
                    "legal_entity_id": entity,
                    "meter_id": "meter-1",
                    "asset_id": "asset-1",
                    "location_id": "location-1",
                    "measurement_type": "FLOW",
                    "unit": "M3",
                    "pressure_basis": "ABS",
                    "temperature_basis": "15C",
                    "measurement_timestamp": "2025-01-01T00:00:00+00:00",
                    "value": "10",
                },
            ),
            FakeResource(
                UUID("90000000-0000-0000-0000-000000000002"),
                {
                    "legal_entity_id": entity,
                    "meter_id": "meter-1",
                    "asset_id": "asset-1",
                    "location_id": "location-1",
                    "measurement_type": "FLOW",
                    "unit": "M3",
                    "pressure_basis": "ABS",
                    "temperature_basis": "15C",
                    "measurement_timestamp": "2025-01-01T01:00:00+00:00",
                    "value": "12",
                },
            ),
            FakeResource(
                UUID("90000000-0000-0000-0000-000000000003"),
                {
                    "legal_entity_id": entity,
                    "meter_id": "meter-1",
                    "asset_id": "asset-1",
                    "location_id": "location-1",
                    "measurement_type": "FLOW",
                    "unit": "M3",
                    "pressure_basis": "ABS",
                    "temperature_basis": "15C",
                    "measurement_timestamp": "2025-01-01T05:00:00+00:00",
                    "value": "18",
                },
            ),
        ]
    }
    monkeypatch.setattr(
        petroleum_reconciliation.resources,
        "list_resources",
        lambda _p, kind, _s, _o, limit=5000: rows[kind],
    )
    result = petroleum_reconciliation.telemetry(_principal())
    assert result["contract"] == "petroleum-telemetry-bridge/1"
    assert result["rows"][0]["status"] == "GAP_REVIEW_REQUIRED"
    assert result["rows"][0]["gap_count"] == 1
    assert result["rows"][0]["basis_state"] == "COMPLETE"
    assert result["live_connector"] is False

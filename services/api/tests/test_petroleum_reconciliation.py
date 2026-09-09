from uuid import UUID

from finai_api.services import petroleum_reconciliation


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

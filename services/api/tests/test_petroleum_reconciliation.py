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

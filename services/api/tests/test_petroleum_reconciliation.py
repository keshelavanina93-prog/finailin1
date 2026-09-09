from uuid import UUID

from finai_api.services import petroleum_reconciliation


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
            type(
                "R",
                (),
                {
                    "attributes": {
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
                    }
                },
            )()
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

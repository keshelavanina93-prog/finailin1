from types import SimpleNamespace
from uuid import UUID

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services import operational_binding_validation

SCOPE = ExactScope(
    tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
    legal_entity_id="entity-ge-001",
    period="2026-08",
    currency="GEL",
)
PRINCIPAL = Principal(
    actor_id="test-actor",
    display_name="Test Actor",
    scope=SCOPE,
    permissions=("ontology_read",),
)


def receipt(
    values: dict[str, str], profile: str = "orpak-forecourt-sale-line/1"
) -> SimpleNamespace:
    candidate = SimpleNamespace(object_type="SourceRecord", source_row=2, values=values)
    return SimpleNamespace(
        receipt_id="receipt-1", source_profile={"profile": profile}, candidates=(candidate,)
    )


def resource(object_type: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(object_type=object_type, attributes={"code": value})


def valid_orpak_values() -> dict[str, str]:
    return {
        "station_id": "ST-1",
        "dispenser_id": "D-2",
        "nozzle_id": "N-1",
        "product_code": "DIESEL",
        "transaction_id": "TX-1",
        "event_time": "2026-08-12T10:00:00+04:00",
        "quantity": "1250.50",
        "unit": "L",
        "unit_price": "3.20",
        "gross_amount": "4001.60",
        "payment_method": "CARD",
        "currency": "GEL",
        "source_record_id": "ROW-1",
        "source_hash": "a" * 64,
        "operational_validation": '{"reasons": []}',
    }


def test_binding_validation_resolves_accepted_orpak_dimensions(monkeypatch):
    values = valid_orpak_values()
    monkeypatch.setattr(
        operational_binding_validation, "retrieve", lambda scope, receipt_id: receipt(values)
    )
    monkeypatch.setattr(
        operational_binding_validation.resources,
        "list_resources",
        lambda principal, object_type, query, offset, limit: [
            resource(object_type, values[field])
            for field, mapped_type in operational_binding_validation.LOOKUPS["ORPAK"].items()
            if mapped_type == object_type
        ],
    )

    result = operational_binding_validation.validate(PRINCIPAL, "receipt-1")

    assert result["status"] == "VALIDATED"
    assert result["promotion_eligible"] is False
    assert all(result["rows"][0]["bindings"].values())


def test_binding_validation_requires_gas_meter_bindings(monkeypatch):
    values = {
        "meter_id": "M-1",
        "asset_id": "A-1",
        "location_id": "L-1",
        "operational_validation": '{"reasons": []}',
    }
    monkeypatch.setattr(
        operational_binding_validation,
        "retrieve",
        lambda scope, receipt_id: receipt(values, "gas-telemetry-measurement/1"),
    )
    monkeypatch.setattr(
        operational_binding_validation.resources, "list_resources", lambda *args, **kwargs: []
    )

    result = operational_binding_validation.validate(PRINCIPAL, "receipt-1")

    assert result["profile"] == "gas-telemetry-measurement/1"
    assert result["status"] == "REVIEW_REQUIRED"
    assert "UNBOUND_METER_ID" in result["rows"][0]["reasons"]

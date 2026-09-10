from types import SimpleNamespace
from uuid import UUID, uuid4

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
        receipt_id="receipt-1",
        source_sha256="b" * 64,
        scope=SCOPE,
        source_profile={"profile": profile},
        candidates=(candidate,),
    )


def resource(object_type: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(
        object_type=object_type, resource_id=uuid4(), version_id=uuid4(), attributes={"code": value}
    )


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
    assert result["promotion_eligible"] is True
    assert result["canonical_promotion"] == "GOVERNED_REVIEW_REQUIRED"
    assert result["source_system"] == "ORPAK"
    assert result["grain"] == "ONE_FORECOURT_SALE_LINE"
    assert result["validation_stage"] == "SEMANTIC_BINDING"
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
    assert result["source_system"] == "GAS_TELEMETRY"
    assert result["grain"] == "ONE_METER_MEASUREMENT_AT_ONE_TIME"
    assert result["status"] == "REVIEW_REQUIRED"
    assert "UNBOUND_METER_ID" in result["rows"][0]["reasons"]


def test_binding_validation_resolves_retail_store_and_cash_register(monkeypatch):
    values = {
        "store_id": "STORE-1",
        "cash_register_id": "TILL-2",
        "operational_validation": '{"reasons": []}',
    }
    monkeypatch.setattr(
        operational_binding_validation,
        "retrieve",
        lambda scope, receipt_id: receipt(values, "retail-cash-register-shift-close/1"),
    )
    monkeypatch.setattr(
        operational_binding_validation.resources,
        "list_resources",
        lambda principal, object_type, query, offset, limit: [
            resource(
                object_type, values["store_id" if object_type == "Store" else "cash_register_id"]
            )
        ],
    )

    result = operational_binding_validation.validate(PRINCIPAL, "receipt-1")

    assert result["status"] == "VALIDATED"
    assert result["promotion_eligible"] is True


def test_promotion_preview_is_proposal_only_and_preserves_evidence(monkeypatch):
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

    result = operational_binding_validation.promotion_preview(PRINCIPAL, "receipt-1")

    assert result["status"] == "READY_FOR_GOVERNED_PROPOSAL"
    assert result["proposal_required"] is True
    assert result["canonical_mutation"] is False
    assert result["grain"] == "ONE_FORECOURT_SALE_LINE"
    assert result["candidates"][0]["object_type"] == "RetailSale"
    assert result["candidates"][0]["evidence"]["source_record_id"] == "ROW-1"


def test_submit_governed_proposal_persists_review_packet_without_promotion(monkeypatch):
    values = valid_orpak_values()
    principal = Principal(
        actor_id="maker",
        display_name="Maker",
        scope=SCOPE,
        permissions=("ontology_read", "ontology_propose"),
    )
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
    monkeypatch.setattr(
        operational_binding_validation.resources,
        "current_resources",
        lambda *args, **kwargs: {},
    )
    captured = {}
    monkeypatch.setattr(
        operational_binding_validation.resources,
        "propose",
        lambda _principal, proposal: captured.setdefault("proposal", proposal),
    )
    result = operational_binding_validation.submit_governed_proposal(principal, "receipt-1")
    proposal = captured["proposal"]
    assert result is proposal
    assert proposal.mutations[0].object_type == "SourceEvidence"
    sale = proposal.mutations[1]
    assert sale.object_type == "RetailSale"
    assert sale.evidence_class == "SOURCE_BOUND"
    assert sale.attributes["evidence_id"] == str(proposal.mutations[0].resource_id)
    assert sale.attributes["source_details"]["source_record_id"] == "ROW-1"

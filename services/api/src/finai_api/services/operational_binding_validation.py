"""Resolve operational source identifiers against accepted ontology resources."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from finai_api.domain.resources import ProposalDetail, ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import retrieve

LOOKUPS = {
    "ORPAK": {
        "station_id": "Station",
        "product_code": "Product",
        "dispenser_id": "Dispenser",
        "nozzle_id": "Nozzle",
    },
    "SCADA": {"meter_id": "Meter", "asset_id": "Asset", "location_id": "Location"},
    "GAS_TELEMETRY": {"meter_id": "Meter", "asset_id": "Asset", "location_id": "Location"},
    "RETAIL_CASH_REGISTER": {"store_id": "Store", "cash_register_id": "CashRegister"},
    "MOVEMENT_REGISTER": {
        "source_location_id": "Location",
        "destination_location_id": "Location",
        "product_code": "Product",
    },
}


def _matches(resource: Any, value: str) -> bool:
    attrs = resource.attributes
    return value in {
        str(attrs.get(key)) for key in ("code", "external_id", "identifier", "reference")
    }


def validate(principal: Principal, receipt_id: str) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    receipt = retrieve(principal.scope, receipt_id)
    if receipt is None:
        raise WorkspaceError(404, "Operational intake receipt unavailable in authorized scope")
    source_system = str(receipt.source_profile.get("source_system", ""))
    profile = str(receipt.source_profile.get("profile", ""))
    source_system = (
        "ORPAK"
        if profile.startswith("orpak-")
        else "GAS_TELEMETRY"
        if profile.startswith("gas-telemetry-")
        else "SCADA"
        if profile.startswith("scada-")
        else "RETAIL_CASH_REGISTER"
        if profile.startswith("retail-cash-register-")
        else "MOVEMENT_REGISTER"
        if profile.startswith("1c-movement-register-")
        else source_system.upper()
    )
    lookup = LOOKUPS.get(source_system)
    if lookup is None:
        raise WorkspaceError(409, "Receipt is not an ORPAK or gas telemetry operational profile")
    accepted: dict[str, list[Any]] = {
        object_type: resources.list_resources(principal, object_type, "", 0, limit=1000)
        for object_type in set(lookup.values())
    }
    rows = []
    for candidate in receipt.candidates:
        if candidate.object_type != "SourceRecord":
            continue
        values = candidate.values
        reasons: list[str] = []
        bindings: dict[str, bool] = {}
        for field, object_type in lookup.items():
            value = str(values.get(field, ""))
            bound = bool(value) and any(_matches(item, value) for item in accepted[object_type])
            bindings[field] = bound
            if not bound:
                reasons.append(f"UNBOUND_{field.upper()}")
        raw = values.get("operational_validation", "{}")
        try:
            structural = json.loads(raw) if isinstance(raw, str) else {}
        except json.JSONDecodeError:
            structural = {}
            reasons.append("INVALID_RETAINED_VALIDATION")
        reasons.extend(structural.get("reasons", []))
        rows.append(
            {
                "source_row": candidate.source_row,
                "status": "VALIDATED" if not reasons else "REVIEW_REQUIRED",
                "bindings": bindings,
                "reasons": sorted(set(reasons)),
                "promotion_eligible": not reasons,
            }
        )
    promotion_eligible = bool(rows) and all(row["promotion_eligible"] for row in rows)
    return {
        "contract": "operational-binding-validation/1",
        "receipt_id": receipt.receipt_id,
        "profile": profile,
        "rows": rows,
        "status": "VALIDATED"
        if rows and all(row["status"] == "VALIDATED" for row in rows)
        else "REVIEW_REQUIRED",
        "promotion_eligible": promotion_eligible,
        "canonical_promotion": "GOVERNED_REVIEW_REQUIRED",
        "accounting_authorized": False,
        "business_effect_authorized": False,
    }


def promotion_preview(principal: Principal, receipt_id: str) -> dict[str, Any]:
    """Compile eligible retained rows into a proposal-only canonical payload preview."""
    report = validate(principal, receipt_id)
    receipt = retrieve(principal.scope, receipt_id)
    assert receipt is not None
    profile = str(report["profile"])
    source_system = (
        "ORPAK"
        if profile.startswith("orpak-")
        else "GAS_TELEMETRY"
        if profile.startswith("gas-telemetry-")
        else "SCADA"
        if profile.startswith("scada-")
        else "RETAIL_CASH_REGISTER"
        if profile.startswith("retail-cash-register-")
        else "MOVEMENT_REGISTER"
        if profile.startswith("1c-movement-register-")
        else ""
    )
    lookup = LOOKUPS[source_system]
    accepted: dict[str, list[Any]] = {
        object_type: resources.list_resources(principal, object_type, "", 0, limit=1000)
        for object_type in set(lookup.values())
    }
    rows_by_source = {int(row["source_row"]): row for row in report["rows"]}
    candidates: list[dict[str, Any]] = []
    for candidate in receipt.candidates:
        if candidate.object_type != "SourceRecord":
            continue
        row_report = rows_by_source.get(candidate.source_row)
        if not row_report or not row_report["promotion_eligible"]:
            continue
        values = candidate.values
        refs: dict[str, dict[str, str]] = {}
        for field, object_type in lookup.items():
            match = next(
                (item for item in accepted[object_type] if _matches(item, str(values[field]))),
                None,
            )
            if match is not None:
                refs[field] = {
                    "resource_id": str(match.resource_id),
                    "version_id": str(match.version_id),
                }
        canonical_values: dict[str, Any]
        if source_system == "ORPAK":
            object_type = "RetailSale"
            canonical_values = {
                "transaction_id": values["transaction_id"],
                "station_id": refs["station_id"]["resource_id"],
                "product_id": refs["product_code"]["resource_id"],
                "dispenser_id": refs["dispenser_id"]["resource_id"],
                "nozzle_id": refs["nozzle_id"]["resource_id"],
                "event_time": values["event_time"],
                "quantity": values["quantity"],
                "unit": values["unit"],
                "unit_price": values["unit_price"],
                "gross_amount": values["gross_amount"],
                "payment_method": values["payment_method"],
                "currency": values["currency"],
            }
        elif source_system == "RETAIL_CASH_REGISTER":
            object_type = "CashRegisterShiftClose"
            canonical_values = {
                "store_id": refs["store_id"]["resource_id"],
                "cash_register_id": refs["cash_register_id"]["resource_id"],
                "shift_id": values["shift_id"],
                "operator_id": values["operator_id"],
                "event_time": values["event_time"],
                "z_report_id": values["z_report_id"],
                "fiscal_close_status": values["fiscal_close_status"],
                "currency": values["currency"],
                "gross_amount": values["gross_amount"],
                "net_amount": values["net_amount"],
                "payment_method": values["payment_method"],
            }
        elif source_system == "MOVEMENT_REGISTER":
            object_type = "PhysicalMovement"
            canonical_values = {
                "movement_id": values["movement_id"],
                "movement_type": values["movement_type"],
                "source_location_id": refs["source_location_id"]["resource_id"],
                "destination_location_id": refs["destination_location_id"]["resource_id"],
                "product_id": refs["product_code"]["resource_id"],
                "event_time": values["event_time"],
                "quantity": values["quantity"],
                "unit": values["unit"],
                "document_id": values["document_id"],
            }
        else:
            object_type = "PhysicalMeasurement"
            canonical_values = {
                "meter_id": refs["meter_id"]["resource_id"],
                "asset_id": refs["asset_id"]["resource_id"],
                "location_id": refs["location_id"]["resource_id"],
                "measurement_type": values["measurement_type"],
                "measurement_timestamp": values["measurement_timestamp"],
                "value": values["value"],
                "unit": values["unit"],
                "pressure_basis": values["pressure_basis"],
                "temperature_basis": values["temperature_basis"],
                "quality_status": values["quality_status"],
            }
        canonical_values = {
            "legal_entity_id": str(receipt.scope.legal_entity_id),
            **canonical_values,
            "source_details": {
                "receipt_id": receipt.receipt_id,
                "source_record_id": values["source_record_id"],
                "source_hash": receipt.source_sha256,
                "source_row": candidate.source_row,
            },
        }
        candidates.append(
            {
                "object_type": object_type,
                "identity_key": f"{object_type}:{values['source_record_id']}",
                "source_row": candidate.source_row,
                "values": canonical_values,
                "bindings": refs,
                "evidence": {
                    "receipt_id": receipt.receipt_id,
                    "source_record_id": values["source_record_id"],
                    "source_hash": receipt.source_sha256,
                    "valid_at": str(receipt.scope.period),
                },
            }
        )
    return {
        "contract": "operational-promotion-preview/1",
        "receipt_id": receipt.receipt_id,
        "profile": profile,
        "status": "READY_FOR_GOVERNED_PROPOSAL" if candidates else "NO_ELIGIBLE_ROWS",
        "proposal_required": True,
        "canonical_mutation": False,
        "accounting_authorized": False,
        "business_effect_authorized": False,
        "candidates": candidates,
    }


def submit_governed_proposal(principal: Principal, receipt_id: str) -> ProposalDetail:
    """Persist eligible operational candidates as a reviewable proposal only."""
    require_permission(principal, "ontology_propose")
    preview = promotion_preview(principal, receipt_id)
    if preview["status"] != "READY_FOR_GOVERNED_PROPOSAL":
        raise WorkspaceError(409, "Operational intake has no eligible rows for proposal submission")
    receipt = retrieve(principal.scope, receipt_id)
    assert receipt is not None
    mutations: list[ResourceMutation] = []
    for candidate in preview["candidates"]:
        values = candidate["values"]
        raw_time = values.get("event_time") or values.get("measurement_timestamp")
        if not raw_time:
            raw_time = f"{receipt.scope.period}-01T00:00:00+00:00"
        effective = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        if effective.tzinfo is None:
            effective = effective.replace(tzinfo=UTC)
        source_record_id = candidate["evidence"]["source_record_id"]
        mutations.append(
            ResourceMutation(
                resource_id=uuid5(NAMESPACE_URL, f"g8:{receipt.receipt_id}:{source_record_id}"),
                object_type=candidate["object_type"],
                identity_key=candidate["identity_key"],
                display_name=f"{candidate['object_type']} · {source_record_id}",
                attributes=values,
                valid_from=effective,
                evidence_class="SOURCE_BOUND",
            )
        )
    proposal = ResourceProposal(
        proposal_id=uuid5(NAMESPACE_URL, f"g8-operational-proposal:{receipt.receipt_id}"),
        title=f"Operational intake proposal · {receipt.receipt_id}",
        rationale=(
            "Submit validated, semantically bound operational observations for "
            "independent governed review; intake performs no canonical mutation."
        ),
        access_entity=str(principal.scope.legal_entity_id),
        mutations=mutations,
    )
    return resources.propose(principal, proposal)

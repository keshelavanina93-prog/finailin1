"""Resolve operational source identifiers against accepted ontology resources."""

import json
from typing import Any

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

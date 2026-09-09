"""Structural, grain and evidence validation for industrial source rows.

Validation here deliberately stops before ontology promotion. A row can be
well-formed and still require governed binding to accepted Station, Product,
Meter, Tank and company resources.
"""

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

ORPAK_PROFILE = "orpak-forecourt-sale-line/1"
GAS_PROFILE = "gas-telemetry-measurement/1"
RETAIL_PROFILE = "retail-cash-register-shift-close/1"
ORPAK_REQUIRED = frozenset(
    {
        "station_id",
        "dispenser_id",
        "nozzle_id",
        "product_code",
        "transaction_id",
        "event_time",
        "quantity",
        "unit",
        "unit_price",
        "gross_amount",
        "payment_method",
        "currency",
        "source_record_id",
        "source_hash",
    }
)
GAS_REQUIRED = frozenset(
    {
        "meter_id",
        "asset_id",
        "location_id",
        "measurement_type",
        "measurement_timestamp",
        "value",
        "unit",
        "pressure_basis",
        "temperature_basis",
        "quality_status",
        "source_system",
        "source_record_id",
        "source_hash",
    }
)
RETAIL_REQUIRED = frozenset(
    {
        "store_id",
        "cash_register_id",
        "shift_id",
        "operator_id",
        "event_time",
        "z_report_id",
        "fiscal_close_status",
        "currency",
        "gross_amount",
        "net_amount",
        "payment_method",
        "source_record_id",
        "source_hash",
    }
)
UNITS = frozenset({"L", "LITER", "LITERS", "M3", "KG", "TONNE", "TONNES"})
HASH = re.compile(r"^[a-fA-F0-9]{64}$")


def profile_for(source_system: str | None) -> dict[str, Any] | None:
    key = source_system.upper() if source_system else ""
    if key == "ORPAK":
        return {
            "profile": ORPAK_PROFILE,
            "grain": "ONE_FORECOURT_SALE_LINE",
            "required": ORPAK_REQUIRED,
        }
    if key in {"SCADA", "GAS_TELEMETRY"}:
        return {
            "profile": GAS_PROFILE,
            "grain": "ONE_METER_MEASUREMENT_AT_ONE_TIME",
            "required": GAS_REQUIRED,
        }
    if key in {"RETAIL_CASH_REGISTER", "CASH_REGISTER", "RETAIL_POS"}:
        return {
            "profile": RETAIL_PROFILE,
            "grain": "ONE_CASH_REGISTER_SHIFT_CLOSE",
            "required": RETAIL_REQUIRED,
        }
    return None


def _decimal(
    row: dict[str, str], name: str, reasons: list[str], *, nonnegative: bool = True
) -> Decimal | None:
    try:
        value = Decimal(row.get(name, ""))
    except InvalidOperation:
        reasons.append("INVALID_DECIMAL")
        return None
    if not value.is_finite() or (nonnegative and value < 0):
        reasons.append("OUT_OF_RANGE_READING")
        return None
    return value


def _time(row: dict[str, str], name: str, reasons: list[str]) -> None:
    try:
        parsed = datetime.fromisoformat(row.get(name, ""))
    except ValueError:
        reasons.append("INVALID_TIMESTAMP")
        return
    if parsed.tzinfo is None:
        reasons.append("TIMESTAMP_TIMEZONE_REQUIRED")


def validate_row(source_system: str, row: dict[str, str], seen: set[str]) -> dict[str, Any]:
    contract = profile_for(source_system)
    assert contract is not None
    reasons: list[str] = []
    missing = sorted(name for name in contract["required"] if not row.get(name, "").strip())
    reasons.extend("MISSING_" + name.upper() for name in missing)
    if not missing:
        if not HASH.fullmatch(row["source_hash"]):
            reasons.append("INVALID_SOURCE_HASH")
        if "unit" in row and row["unit"].upper() not in UNITS:
            reasons.append("UNKNOWN_UNIT")
        if not row["source_record_id"].strip():
            reasons.append("MISSING_SOURCE_ID")
        identity_fields: tuple[str, ...]
        if source_system.upper() == "ORPAK":
            identity_fields = (
                row["transaction_id"],
                row["station_id"],
                row["nozzle_id"],
                row["event_time"],
            )
        elif source_system.upper() in {"SCADA", "GAS_TELEMETRY"}:
            identity_fields = (
                row["meter_id"],
                row["measurement_timestamp"],
                row["measurement_type"],
            )
        else:
            identity_fields = (
                row["store_id"],
                row["cash_register_id"],
                row["shift_id"],
                row["event_time"],
            )
        identity = sha256("|".join(identity_fields).encode()).hexdigest()
        if identity in seen:
            reasons.append("DUPLICATE_EVENT")
        seen.add(identity)
        _time(
            row,
            "event_time"
            if source_system.upper()
            in {"ORPAK", "RETAIL_CASH_REGISTER", "CASH_REGISTER", "RETAIL_POS"}
            else "measurement_timestamp",
            reasons,
        )
        if source_system.upper() == "ORPAK":
            _decimal(row, "quantity", reasons)
            _decimal(row, "unit_price", reasons)
            _decimal(row, "gross_amount", reasons)
            if not re.fullmatch(r"[A-Z]{3}", row["currency"]):
                reasons.append("INVALID_CURRENCY")
        elif source_system.upper() in {"SCADA", "GAS_TELEMETRY"}:
            _decimal(row, "value", reasons)
            if not row["pressure_basis"].strip() or not row["temperature_basis"].strip():
                reasons.append("MISSING_MEASUREMENT_BASIS")
        else:
            _decimal(row, "gross_amount", reasons)
            _decimal(row, "net_amount", reasons)
            if not re.fullmatch(r"[A-Z]{3}", row["currency"]):
                reasons.append("INVALID_CURRENCY")
            fiscal_status = row["fiscal_close_status"].upper()
            if fiscal_status not in {"CLOSED", "REOPENED"}:
                reasons.append("FISCAL_CLOSE_NOT_CONFIRMED")
            elif fiscal_status == "REOPENED":
                reasons.append("FISCAL_CLOSE_REOPENED")
    return {
        "status": "REJECTED" if reasons else "REVIEW_REQUIRED",
        "reasons": sorted(set(reasons)),
        "grain": contract["grain"],
        "binding_status": "UNRESOLVED",
        "promotion_eligible": False,
        "row_identity": sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def validate_series(
    source_system: str, rows: list[dict[str, str]], validations: list[dict[str, Any]]
) -> None:
    """Apply checks that require the complete measurement series, not one row."""
    if source_system.upper() not in {"SCADA", "GAS_TELEMETRY"}:
        return
    previous: dict[str, datetime] = {}
    for row, validation in zip(rows, validations, strict=True):
        if validation["status"] == "REJECTED":
            continue
        try:
            timestamp = datetime.fromisoformat(row["measurement_timestamp"])
        except ValueError:
            continue
        meter = row["meter_id"].strip()
        if meter in previous and timestamp < previous[meter]:
            validation["reasons"] = sorted(set(validation["reasons"]) | {"NON_MONOTONIC_SERIES"})
            validation["status"] = "REVIEW_REQUIRED"
        previous[meter] = timestamp

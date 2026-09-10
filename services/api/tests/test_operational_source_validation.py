from finai_api.services.operational_source_validation import (
    GAS_PROFILE,
    MOVEMENT_PROFILE,
    ORPAK_PROFILE,
    RETAIL_PROFILE,
    profile_for,
    validate_row,
    validate_series,
)


def _orpak() -> dict[str, str]:
    return {
        "station_id": "ST-1",
        "dispenser_id": "D-1",
        "nozzle_id": "N-1",
        "product_code": "DIESEL",
        "transaction_id": "TX-1",
        "event_time": "2026-08-12T10:00:00+04:00",
        "quantity": "10.50",
        "unit": "L",
        "unit_price": "3.20",
        "gross_amount": "33.60",
        "payment_method": "CARD",
        "currency": "GEL",
        "source_record_id": "ROW-1",
        "source_hash": "a" * 64,
    }


def _gas() -> dict[str, str]:
    return {
        "meter_id": "M-1",
        "asset_id": "A-1",
        "location_id": "L-1",
        "measurement_type": "FLOW",
        "measurement_timestamp": "2026-08-12T10:00:00+04:00",
        "value": "42.5",
        "unit": "M3",
        "pressure_basis": "ABSOLUTE",
        "temperature_basis": "15C",
        "quality_status": "GOOD",
        "source_system": "SCADA",
        "source_record_id": "READ-1",
        "source_hash": "b" * 64,
    }


def test_profiles_define_business_grain_for_supported_sources():
    assert profile_for("ORPAK") == {
        "profile": ORPAK_PROFILE,
        "grain": "ONE_FORECOURT_SALE_LINE",
        "required": profile_for("ORPAK")["required"],
    }
    assert profile_for("SCADA")["profile"] == GAS_PROFILE
    assert profile_for("RETAIL_POS")["profile"] == RETAIL_PROFILE
    assert profile_for("1C_MOVEMENTS")["profile"] == MOVEMENT_PROFILE
    assert profile_for("unknown") is None


def test_valid_orpak_row_is_review_required_and_never_promotable():
    result = validate_row("ORPAK", _orpak(), set())
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["grain"] == "ONE_FORECOURT_SALE_LINE"
    assert result["binding_status"] == "UNRESOLVED"
    assert result["promotion_eligible"] is False
    assert len(result["row_identity"]) == 64


def test_orpak_validation_reports_missing_and_invalid_dimensions():
    row = _orpak()
    row.update(
        unit="BARREL",
        quantity="-2",
        event_time="2026-08-12T10:00:00",
        currency="lari",
        source_hash="bad",
    )
    result = validate_row("ORPAK", row, set())
    assert result["status"] == "REJECTED"
    assert {
        "UNKNOWN_UNIT",
        "INVALID_SOURCE_HASH",
        "TIMESTAMP_TIMEZONE_REQUIRED",
        "OUT_OF_RANGE_READING",
        "INVALID_CURRENCY",
    } <= set(result["reasons"])
    missing = _orpak()
    missing["station_id"] = ""
    assert "MISSING_STATION_ID" in validate_row("ORPAK", missing, set())["reasons"]


def test_duplicate_identity_is_detected_even_when_rows_are_well_formed():
    seen: set[str] = set()
    first = validate_row("ORPAK", _orpak(), seen)
    second = validate_row("ORPAK", _orpak(), seen)
    assert "DUPLICATE_EVENT" not in first["reasons"]
    assert "DUPLICATE_EVENT" in second["reasons"]


def test_gas_validation_requires_basis_quality_and_detects_series_findings():
    first = _gas()
    second = _gas() | {
        "source_record_id": "READ-2",
        "measurement_timestamp": "2026-08-12T09:00:00+04:00",
    }
    first_result = validate_row("GAS_TELEMETRY", first, set())
    second_result = validate_row("SCADA", second, set())
    second_result["reasons"].append("MISSING_MEASUREMENT_BASIS")
    validations = [first_result, second_result]
    validate_series("SCADA", [first, second], validations)
    assert validations[1]["status"] == "REVIEW_REQUIRED"
    assert "NON_MONOTONIC_SERIES" in validations[1]["reasons"]
    unknown = _gas() | {"quality_status": "INFERRED"}
    assert "UNKNOWN_QUALITY_STATUS" in validate_row("SCADA", unknown, set())["reasons"]


def test_gas_series_marks_inferred_gap_for_review():
    rows = [
        _gas(),
        _gas()
        | {"source_record_id": "READ-2", "measurement_timestamp": "2026-08-12T10:01:00+04:00"},
        _gas()
        | {"source_record_id": "READ-3", "measurement_timestamp": "2026-08-12T10:02:00+04:00"},
        _gas()
        | {"source_record_id": "READ-4", "measurement_timestamp": "2026-08-12T10:05:00+04:00"},
    ]
    validations = [validate_row("SCADA", row, set()) for row in rows]
    validate_series("SCADA", rows, validations)
    assert "MEASUREMENT_GAP" in validations[3]["reasons"]


def test_retail_and_movement_profiles_apply_domain_checks():
    retail = {
        "store_id": "S-1", "cash_register_id": "R-1", "shift_id": "SH-1",
        "operator_id": "O-1", "event_time": "2026-08-12T10:00:00+00:00",
        "z_report_id": "Z-1", "fiscal_close_status": "REOPENED", "currency": "GEL",
        "gross_amount": "10", "net_amount": "9", "payment_method": "CASH",
        "source_record_id": "ROW-1", "source_hash": "c" * 64,
    }
    movement = {
        "movement_id": "MV-1", "movement_type": "TRANSFER", "source_location_id": "A",
        "destination_location_id": "B", "product_code": "P",
        "event_time": "2026-08-12T10:00:00+00:00",
        "quantity": "-1", "unit": "L", "document_id": "DOC-1", "source_record_id": "ROW-2",
        "source_hash": "d" * 64,
    }
    retail_result = validate_row("RETAIL_POS", retail, set())
    movement_result = validate_row("MOVEMENT_REGISTER", movement, set())
    assert "FISCAL_CLOSE_REOPENED" in retail_result["reasons"]
    assert "OUT_OF_RANGE_READING" in movement_result["reasons"]

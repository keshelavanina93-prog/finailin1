from uuid import UUID

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestRequest
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source

SCOPE = ExactScope(
    tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
    legal_entity_id="entity-ge-001",
    period="2026-08",
    currency="GEL",
)


def request(source_system: str, csv_text: str) -> IngestRequest:
    return IngestRequest(
        scope=SCOPE,
        filename=f"{source_system.lower()}.csv",
        csv_text=csv_text,
        source_system=source_system,
    )


def test_orpak_profile_retains_forecourt_grain_without_financial_promotion():
    result = compile_source(
        request(
            "ORPAK",
            "station_id,dispenser_id,nozzle_id,product_code,transaction_id,event_time,quantity,unit,unit_price,gross_amount,payment_method,currency,source_record_id,source_hash\n"
            "ST-1,D-2,N-1,DIESEL,TX-1,2026-08-12T10:00:00+04:00,1250.50,L,3.20,4001.60,CARD,GEL,ROW-1,"
            + "a" * 64
            + "\n",
        )
    )
    assert result.source_profile["profile"] == "orpak-forecourt-sale-line/1"
    assert result.source_profile["grain"] == "ONE_FORECOURT_SALE_LINE"
    assert result.source_profile["validation"]["status"] == "REVIEW_REQUIRED"
    assert result.source_profile["validation"]["promotion_eligible"] is False
    assert result.authority_contract_version == "orpak-forecourt-sale-line/1"
    assert result.candidates[0].values["operational_grain"] == "ONE_FORECOURT_SALE_LINE"
    assert result.authority_state == "MAPPED_CANDIDATE"


def test_scada_profile_rejects_missing_source_record_identity():
    with pytest.raises(SourceAuthorityDenied, match="source_record_id"):
        compile_source(
            request(
                "SCADA",
                "meter_id,asset_id,location_id,measurement_type,measurement_timestamp,value,unit,pressure_basis,temperature_basis,quality_status,source_system,source_hash\n"
                "M-1,A-1,L-1,LEVEL,2026-08-12T10:00:00+04:00,10,M3,ABSOLUTE,AMBIENT,GOOD,SCADA,"
                + "a" * 64
                + "\n",
            )
        )


def test_scada_profile_flags_non_monotonic_meter_series_for_review():
    result = compile_source(
        request(
            "SCADA",
            "meter_id,asset_id,location_id,measurement_type,measurement_timestamp,value,unit,pressure_basis,temperature_basis,quality_status,source_system,source_record_id,source_hash\n"
            "M-1,A-1,L-1,LEVEL,2026-08-12T10:00:00+04:00,10,M3,ABSOLUTE,AMBIENT,GOOD,SCADA,ROW-1,"
            + "a"
            * 64
            + "\n"
            "M-1,A-1,L-1,LEVEL,2026-08-12T09:00:00+04:00,9,M3,ABSOLUTE,AMBIENT,GOOD,SCADA,ROW-2,"
            + "b" * 64
            + "\n",
        )
    )
    assert result.source_profile["validation"]["rows"][1]["status"] == "REVIEW_REQUIRED"
    assert "NON_MONOTONIC_SERIES" in result.source_profile["validation"]["rows"][1]["reasons"]


def test_retail_cash_register_profile_retains_shift_close_as_review_candidate():
    result = compile_source(
        request(
            "RETAIL_CASH_REGISTER",
            "store_id,cash_register_id,shift_id,operator_id,event_time,z_report_id,fiscal_close_status,currency,gross_amount,net_amount,payment_method,source_record_id,source_hash\n"
            "STORE-1,TILL-2,SHIFT-9,OP-4,2026-08-12T22:00:00+04:00,Z-2026-08-12,CLOSED,GEL,1200.00,1180.00,CARD,Z-ROW-1,"
            + "a" * 64
            + "\n",
        )
    )
    assert result.source_profile["profile"] == "retail-cash-register-shift-close/1"
    assert result.source_profile["grain"] == "ONE_CASH_REGISTER_SHIFT_CLOSE"
    assert result.source_profile["validation"]["promotion_eligible"] is False
    assert result.candidates[0].values["operational_grain"] == "ONE_CASH_REGISTER_SHIFT_CLOSE"

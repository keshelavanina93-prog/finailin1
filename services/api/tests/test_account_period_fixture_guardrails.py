"""CI guardrails for a permanent multi-period, unmapped-row fixture."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestRequest
from finai_api.services.finance_chartpack import classification_manifest
from finai_api.services.independent_tb_reader import TBControl, TBFingerprint, TBMonth, TBRow
from finai_api.services.ingestion import compile_source
from finai_api.services.tb_continuity import continuity_report

FIXTURE = Path(__file__).parent / "fixtures" / "account-period-2025.json"


def _fixture() -> dict:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert value["contract"] == "account-period-fixture/1"
    assert value["authority"] == "TEST_ONLY"
    assert len(value["periods"]) == 12
    actual_periods = [row["period"] for row in value["periods"]]
    expected_periods = [f"2025-{month:02d}" for month in range(1, 13)]
    assert actual_periods == expected_periods
    return value


def _months(value: dict) -> list[TBMonth]:
    months = []
    for item in value["periods"]:
        period = item["period"]
        start = date.fromisoformat(period + "-01")
        row = TBRow(
            source_row=7,
            account_code="6110",
            account_name="Revenue candidate",
            subkonto=None,
            outline_level=0,
            outline_role="root",
            parent_row=None,
            parent_code=None,
            amounts={
                "opening_debit": Decimal(item["opening"]),
                "opening_credit": Decimal(0),
                "turnover_debit": Decimal(item["turnover"]),
                "turnover_credit": Decimal(0),
                "closing_debit": Decimal(item["closing"]),
                "closing_credit": Decimal(0),
            },
            coordinates={},
            source_cells=(),
        )
        amounts = dict(row.amounts)
        months.append(
            TBMonth(
                filename=f"sanitized-{period}.json",
                source_sha256=sha256(period.encode()).hexdigest(),
                sheet="TB",
                company_heading="Sanitized fixture company",
                title_heading="Trial balance",
                period_heading=period,
                data_mode_heading="TEST_ONLY",
                period=period,
                period_start=start,
                period_end=date(start.year, start.month, 28),
                rows=(row,),
                control=TBControl(source_row=7, amounts=amounts, coordinates={}),
                fingerprint=TBFingerprint(
                    digest="b" * 64,
                    measure_columns=(),
                    outline_levels=(0,),
                    outline_shape=((0, 1),),
                    account_codes=("6110",),
                    heading_language=("LATIN",),
                ),
            )
        )
    return months


def test_fixture_catches_adjacent_period_drift_without_repairing_it():
    value = _fixture()
    months = _months(value)
    assert continuity_report(months)["status"] == "CONTINUOUS_REVIEWED"
    changed = replace(
        months[9],
        rows=(
            replace(
                months[9].rows[0],
                amounts={**months[9].rows[0].amounts, "opening_debit": Decimal("551.00")},
            ),
        ),
        control=replace(
            months[9].control,
            amounts={**months[9].control.amounts, "opening_debit": Decimal("551.00")},
        ),
    )
    report = continuity_report([*months[:9], changed, *months[10:]])
    assert report["status"] == "BREAKS_OPEN"
    assert any(
        item["period_from"] == "2025-09" and item["period_to"] == "2025-10"
        for item in report["breaks"]
    )


def test_fixture_preserves_unknown_account_and_subkonto_as_observations():
    value = _fixture()
    manifest = classification_manifest(
        value["rows"],
        source_family=value["source_family"],
        source_hashes=["a" * 64],
    )
    assert manifest["authority"] == "CANDIDATE_ONLY"
    assert manifest["unmapped_account_count"] == 1
    assert manifest["unmapped_subkonto_count"] == 1
    assert {item["code"] for item in manifest["observation_findings"]} == {
        "UNMAPPED_ACCOUNT_CODE",
        "UNMAPPED_SUBKONTO",
    }


def test_generic_intake_keeps_unknown_account_as_candidate_observation():
    request = IngestRequest(
        scope=ExactScope(
            tenant_id="805d8a32-d12b-4268-a236-b0b16e59da9f",
            legal_entity_id="fixture-company",
            period="2025-01",
            currency="GEL",
        ),
        filename="sanitized.csv",
        csv_text="account_code,debit,credit,subkonto\n9999,1,0,unconfigured\n",
    )
    receipt = compile_source(request)
    assert receipt.authority_state == "MAPPED_CANDIDATE"
    assert receipt.reconciliation["status"] == "REVIEW_REQUIRED"
    assert receipt.candidates[0].values["account_code"] == "9999"

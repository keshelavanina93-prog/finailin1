"""Pure integration checks for the generic ACCOUNT_PERIOD TB draft."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services import tb_finance_draft
from finai_api.services.independent_tb_reader import read_tb_path


@pytest.fixture
def fixture_payload(monkeypatch):
    root = Path(r"D:\download c\TB")
    paths = [root / f"SGP {month}.xls" for month in range(1, 13)]
    if not all(path.is_file() for path in paths):
        pytest.skip("private SGP fixture directory is not available")
    months = tuple(read_tb_path(path) for path in paths)
    receipt_ids = tuple(f"fixture-{index}" for index in range(12))
    metadata = tuple(
        {
            "receipt_id": receipt_id,
            "source_sha256": month.source_sha256,
            "submitted_by": "fixture",
            "source_use": "ACTUAL_INPUT",
            "credential_period": "2026-08",
            "observed_period": month.period,
            "period_authority": "SOURCE_INTERNAL_HEADER",
            "period_coordinate": "TDSheet!C3",
            "ingestion_timestamp": "2026-09-09T00:00:00Z",
            "prior_rejects": [],
        }
        for receipt_id, month in zip(receipt_ids, months, strict=True)
    )

    monkeypatch.setattr(
        tb_finance_draft,
        "_load_months",
        lambda _principal, _receipt_ids: (months, receipt_ids, metadata),
    )
    principal = Principal(
        actor_id="tb-draft-test",
        display_name="TB draft test",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="fixture", period="2026-08", currency="GEL"
        ),
        permissions=("read", "ontology_read", "export"),
    )
    return principal, receipt_ids


def test_draft_uses_heading_period_and_retains_mismatch_finding(fixture_payload):
    principal, receipt_ids = fixture_payload
    result = tb_finance_draft.build_draft(principal, receipt_ids, persist=False)

    assert result["function"] == "tb_statement_draft@v1"
    assert result["period_authority"]["accounting_period"] == "SOURCE_INTERNAL_HEADER"
    assert result["period_authority"]["current_date_used_for_accounting_period"] is False
    assert result["period_authority"]["valid_time_fields"] == [
        "valid_at",
        "period_start",
        "period_end",
    ]
    assert result["period_authority"]["known_time_field"] == "hydration_runs.ingested_at"
    assert [row["period"] for row in result["year_pulse"]] == [
        f"2025-{month:02d}" for month in range(1, 13)
    ]
    findings = result["exceptions"]["period_findings"]
    assert len(findings) == 12
    assert {finding["working_period"] for finding in findings} == {"2026-08"}
    assert {finding["observed_period"] for finding in findings} == {
        f"2025-{month:02d}" for month in range(1, 13)
    }


def test_draft_is_source_linked_and_finance_only(fixture_payload):
    principal, receipt_ids = fixture_payload
    result = tb_finance_draft.build_draft(principal, receipt_ids, persist=False)

    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) < 16_000_000
    assert result["year_pulse"][0]["revenue_month"] == "48832047.44"
    assert result["year_pulse"][0]["cogs_month"] == "37685779.61"
    assert result["receivables_by_analytic"][0]["analytics"] == {
        "site_analytic": 110,
        "counterparty_analytic": 2050,
    }
    assert len(result["account_period_facts"]) == 408
    assert len(result["account_period_analytic_facts"]) == 28410
    assert result["fact_columns"][10:12] == ["source_index", "source_row"]
    assert result["fact_columns"][-2:] == ["valid_at", "known_at"]
    assert result["account_period_facts"][0]["lineage"]["source_sha256"]
    assert result["account_period_facts"][0]["valid_at"] == "2025-01-31"
    assert result["account_period_facts"][0]["known_at"] == "2026-09-09T00:00:00Z"
    assert result["account_period_analytic_facts"][0][10] == 0
    assert result["account_period_analytic_facts"][0][-2:] == [
        "2025-01-31",
        "2026-09-09T00:00:00Z",
    ]
    assert result["exceptions"]["unsupported"] == [
        "canonical_journals",
        "invoices",
        "due_dates",
        "aging",
        "liters",
        "tanks",
        "trucks",
        "product_margin",
        "live_map",
        "GEL_currency_inference",
    ]
    assert result["review"]["certification"] == "NOT_CERTIFIED"
    assert result["review"]["petroleum_actuals"] == "UNIMPLEMENTED"


def test_export_has_not_certified_workbook_and_sidecar(fixture_payload):
    principal, receipt_ids = fixture_payload
    result = tb_finance_draft.build_draft(principal, receipt_ids, persist=False)
    content = tb_finance_draft.export_zip(result)

    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert set(archive.namelist()) == {"TB_Finance_Draft.xlsx", "TB_Finance_Draft.json"}
        sidecar = json.loads(archive.read("TB_Finance_Draft.json"))
    assert sidecar["certification"] == "NOT_CERTIFIED"
    assert sidecar["source_hashes"] == result["lineage"]["source_hashes"]

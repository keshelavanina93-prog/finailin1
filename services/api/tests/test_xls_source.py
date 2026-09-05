"""Authentic private fixture checks run when FINAI_PETROLEUM_FIXTURES is configured."""

import base64
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestRequest
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source
from finai_api.services.xls_source import inspect_xls, preview_xls


def source(month: int = 1) -> IngestRequest:
    folder = os.environ.get("FINAI_PETROLEUM_FIXTURES")
    if not folder:
        pytest.skip("Private source fixture directory is not configured")
    content = (Path(folder) / f"SGP {month}.xls").read_bytes()
    return IngestRequest(
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="source-review",
            currency="GEL",
            period=f"2025-{month:02}",
        ),
        filename="renamed.xls",
        xls_base64=base64.b64encode(content).decode("ascii"),
    )


@pytest.mark.parametrize("month", range(1, 13))
def test_authentic_month_is_observed_from_content_and_no_journal_is_invented(month):
    request = source(month)
    receipt = compile_source(request)
    assert receipt == compile_source(request)
    assert receipt.source_sha256 == sha256(request.source_bytes()).hexdigest()
    assert receipt.observed_bindings["period"] == f"2025-{month:02}"
    assert receipt.source_class == "TRIAL_BALANCE"
    assert not receipt.rejects
    assert receipt.reconciliation["status"] == "REVIEW_REQUIRED"
    assert {c.object_type for c in receipt.candidates} == {"SourceRecord"}
    assert all(
        c.values["aggregation_policy"] == "NON_ADDITIVE_REVIEW_REQUIRED" for c in receipt.candidates
    )
    assert inspect_xls(request.source_bytes())["duplicate_codes"]
    page = preview_xls(request.source_bytes(), 100)
    assert page["sha256"] == receipt.source_sha256
    assert page["rows"][0]["source_row"] == receipt.candidates[100].source_row


def test_period_conflict_and_forbidden_accounting_requests_fail_closed():
    request = source()
    changed = request.model_copy(
        update={"scope": request.scope.model_copy(update={"period": "2026-01"})}
    )
    assert compile_source(changed).rejects
    for kind in ("Invoice", "JournalEntry", "InventoryMovement", "PeriodBalance", "Account"):
        with pytest.raises(SourceAuthorityDenied):
            compile_source(request.model_copy(update={"requested_objects": (kind,)}))
    with pytest.raises(SourceAuthorityDenied):
        compile_source(request.model_copy(update={"context_version_id": uuid4()}))


def test_signed_balances_repeated_headings_and_blank_rows_are_preserved():
    receipt = compile_source(source())
    rows = {c.source_row: c.values for c in receipt.candidates}
    assert rows[10]["opening_debit"] == "-44.21"
    assert rows[19]["source_analytic_label"]
    assert rows[19]["parent_account_candidate"] == "1410"
    assert rows[2917]["turnover_debit"] == "511929505.16"
    assert rows[2917]["turnover_credit"] == "511929505.16"
    assert rows[2917]["source_row_role"] == "UNRESOLVED_ROW"


def test_retained_binary_request_reconstructs_the_same_hash(monkeypatch):
    from finai_api import storage

    request = source()
    run = {
        "request": {
            **request.model_dump(mode="json", exclude={"xls_base64"}),
            "source_encoding": "BIFF_XLS",
        }
    }
    monkeypatch.setattr(storage, "retained_source", lambda scope, run: request.source_bytes())
    restored = storage.retained_request(request.scope, run)
    assert restored == request
    assert compile_source(restored).receipt_id == compile_source(request).receipt_id


def test_binary_validation_rejects_invalid_or_ambiguous_payloads():
    scope = ExactScope(tenant_id=uuid4(), legal_entity_id="a", period="2025-01", currency="GEL")
    for payload in (
        {},
        {"xls_base64": "%%%"},
        {"xls_base64": "YWJj"},
        {"csv_text": "a\n1", "xls_base64": "YWJj"},
    ):
        with pytest.raises(ValueError):
            IngestRequest(scope=scope, filename="source.xls", **payload)
    with pytest.raises(ValueError):
        inspect_xls(b"not an XLS file")

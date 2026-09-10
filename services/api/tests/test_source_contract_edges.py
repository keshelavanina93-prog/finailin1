"""Synthetic BIFF inputs exercise source contracts without private financial fixtures."""

import base64
from hashlib import sha256
from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import pytest
import xlrd
import xlwt

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestRequest
from finai_api.services import company_source, source_account_binding, source_financial_facts
from finai_api.services.ingestion import SourceAuthorityDenied
from finai_api.services.workspace import WorkspaceError
from finai_api.services.xls_source import FIELDS, compile_xls, inspect_xls, preview_xls


def workbook(cells, *, levels=None, second_sheet=False):
    book = xlwt.Workbook()
    sheet = book.add_sheet("Synthetic")
    for (row, column), value in cells.items():
        if isinstance(value, tuple):
            value, number_format = value
            sheet.write(row, column, value, xlwt.easyxf(num_format_str=number_format))
        else:
            sheet.write(row, column, value)
    for row, level in (levels or {}).items():
        sheet.row(row).level = level
    if second_sheet:
        book.add_sheet("Unexpected")
    result = BytesIO()
    book.save(result)
    return result.getvalue()


def tb_cells():
    cells = {
        (0, 2): "SYNTHETIC company",
        (1, 2): "Оборотно-сальдовая ведомость",
        (2, 2): "Период: Февраль 2024 \u0433.",
        (5, 6): "Сальдо на начало периода",
        (5, 10): "Оборот за период",
        (5, 14): "Сальдо на конец периода",
        (6, 2): "Код",
        (6, 3): "Наименование",
        (7, 2): "1XXX",
        (7, 3): "Observed control",
        (7, 6): -12.25,
        (7, 10): 0.3,
        (7, 16): 0,
        (8, 2): "0012.10",
        (8, 3): "First account summary",
        (8, 10): 0.1,
        (9, 4): "Analytic label",
        (9, 10): 0.1,
        (10, 2): "0012.10",
        (10, 3): "Repeated account summary",
        (10, 10): 0.2,
        (11, 0): "Unclassified footer",
    }
    cells.update({(6, c): "Дебет" if k.endswith("debit") else "Кредит" for k, c in FIELDS.items()})
    return cells


def journal_cells():
    return {
        (1, 9): "Company",
        (1, 10): "Dr Account",
        (1, 16): "Cr Account",
        (1, 22): "Сумма",
        (1, 8): "Document",
        (2, 3): 29,
        (2, 4): 2,
        (2, 5): 2024,
        (2, 6): "29.02.2024 23:59:59",
        (2, 8): "SYNTHETIC-JOURNAL-1",
        (2, 9): "SYNTHETIC company",
        (2, 10): (12.1, "0000.00"),
        (2, 16): (1210, "General"),
        (2, 22): -44.21,
    }


def request(content, **changes):
    return IngestRequest(
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="synthetic", period="2024-02", currency="GEL"
        ),
        filename="synthetic.xls",
        xls_base64=base64.b64encode(content).decode("ascii"),
        **changes,
    )


def test_real_biff_trial_balance_preserves_hierarchy_signs_and_duplicate_rows():
    content = workbook(tb_cells(), levels={7: 0, 8: 1, 9: 2, 10: 1, 11: 0})
    observed = inspect_xls(content)
    assert observed["period"] == "2024-02"
    assert observed["duplicate_codes"] == ["0012.10"]
    rows = {r["source_row"]: r["values"] for r in observed["rows"]}
    assert rows[8]["opening_debit"] == "-12.25"
    assert rows[8]["closing_credit"] == "0"
    assert rows[10]["hierarchy_parent_row"] == "9"
    assert rows[10]["parent_account_candidate"] == "0012.10"
    assert rows[10]["analytic_path_candidate"] == "Analytic label"
    assert rows[12]["source_row_role"] == "UNRESOLVED_ROW"
    assert rows[12]["cell_A"] == "Unclassified footer"
    page = preview_xls(content, offset=1, search="summary")
    assert page["total_rows"] == 5 and page["matching_rows"] == 2
    assert page["rows"][0]["source_row"] == 11
    assert page["sha256"] == sha256(content).hexdigest()
    assert page["has_more"] is False


def test_compiler_retains_observations_and_refuses_period_and_posting_authority():
    content = workbook(tb_cells(), levels={7: 0, 8: 1, 9: 2, 10: 1})
    source = request(content)
    receipt = compile_xls(source)
    assert receipt == compile_xls(source)
    assert receipt.source_sha256 == sha256(content).hexdigest()
    assert {item.object_type for item in receipt.candidates} == {"SourceRecord"}
    assert receipt.observed_bindings["company_coordinate"] == "Synthetic!C1"
    assert receipt.observed_bindings["period_coordinate"] == "Synthetic!C3"
    assert receipt.source_profile["financial_promotion"] == "UNAVAILABLE"
    assert not receipt.rejects
    wrong_period = source.model_copy(
        update={"scope": source.scope.model_copy(update={"period": "2025-01"})}
    )
    period_observation = compile_xls(wrong_period)
    assert not period_observation.rejects
    assert period_observation.observed_bindings["period"] == "2024-02"
    assert any("observed heading wins" in warning for warning in period_observation.warnings)
    assert not compile_xls(
        wrong_period.model_copy(update={"source_use": "HISTORICAL_REFERENCE"})
    ).rejects
    for change in (
        {"requested_objects": ("JournalEntry",)},
        {"context_version_id": uuid4()},
        {"account_version_ids": {"0012.10": uuid4()}},
        {"account_alias_version_ids": {"0012.10": uuid4()}},
    ):
        with pytest.raises(SourceAuthorityDenied):
            compile_xls(source.model_copy(update=change))


@pytest.mark.parametrize(
    "change,message",
    [
        ({(6, 2): "Different code header"}, "headers changed"),
        ({(2, 2): "Период: 2024 \u0433."}, "recognized monthly"),
        ({(2, 2): "Период: Unknown 2024 \u0433."}, "recognized monthly"),
        ({(7, 17): "extra populated column"}, "Additional populated"),
    ],
)
def test_trial_balance_adapter_rejects_ambiguous_layout(change, message):
    with pytest.raises(ValueError, match=message):
        inspect_xls(workbook({**tb_cells(), **change}))


@pytest.mark.parametrize(
    "content,message",
    [
        (b"bad", "Unsupported"),
        (bytes.fromhex("d0cf11e0a1b11ae1") + b"broken", "could not be read"),
        (bytes.fromhex("d0cf11e0a1b11ae1") + b"0" * 4_000_000, "Unsupported"),
    ],
    ids=["bad-signature", "corrupt-container", "over-size-limit"],
)
def test_trial_balance_adapter_rejects_non_workbooks(content, message):
    with pytest.raises(ValueError, match=message):
        inspect_xls(content)


def test_trial_balance_adapter_rejects_multiple_sheets_and_small_layout():
    with pytest.raises(ValueError, match="single-sheet"):
        inspect_xls(workbook(tb_cells(), second_sheet=True))
    with pytest.raises(ValueError, match="Unrecognized"):
        inspect_xls(workbook({(0, 0): "small"}))


def test_company_labels_are_text_source_observations_with_original_coordinates():
    content = workbook(
        {(0, 0): "Company", (1, 0): "  Beta  ", (2, 0): "Alpha", (3, 0): "Beta", (4, 1): "orphan"}
    )
    result = company_source.observe_companies(content, "Synthetic", 1, 1)
    assert result["companies"] == [
        {"source_label": "Alpha", "row_count": 1, "first_coordinate": "Synthetic!A3"},
        {"source_label": "Beta", "row_count": 2, "first_coordinate": "Synthetic!A2"},
    ]
    assert result["unassigned_row_count"] == 1
    assert result["authority"] == "SOURCE_COMPANY_LABELS_ONLY"


@pytest.mark.parametrize(
    "cells,header,column,message",
    [
        ({(0, 0): "Company", (1, 0): 12}, 1, 1, "text cells"),
        ({(0, 0): "Company", (1, 0): " "}, 1, 1, "label is empty"),
        ({(0, 0): "Company", (1, 0): "x" * 201}, 1, 1, "exceeds 200"),
        ({(0, 0): "Other", (1, 0): "A"}, 1, 1, "recognized company"),
        ({(1, 0): "A"}, 1, 1, "labelled company"),
        ({(0, 0): "Company", (1, 0): "A"}, 2, 1, "outside"),
        ({(0, 0): "Company", (1, 0): "A"}, 1, 2, "outside"),
    ],
)
def test_company_observation_rejects_ambiguous_columns(cells, header, column, message):
    with pytest.raises(WorkspaceError, match=message):
        company_source.observe_companies(workbook(cells), "Synthetic", header, column)


def test_company_observation_limits_and_missing_sheet():
    cells = {(0, 0): "Company", **{(row, 0): f"Company {row}" for row in range(1, 32)}}
    with pytest.raises(WorkspaceError, match="More than 30"):
        company_source.observe_companies(workbook(cells), "Synthetic", 1, 1)
    with pytest.raises(WorkspaceError, match="cannot be read"):
        company_source.observe_companies(workbook(cells), "Missing", 1, 1)
    with pytest.raises(WorkspaceError, match="BIFF XLS"):
        company_source.observe_companies(b"CSV", "Synthetic", 1, 1)


def test_account_usage_distinguishes_controls_from_exact_account_identities():
    content = workbook(tb_cells())
    usage = source_account_binding.observe_usage(content, "Synthetic", "1c_tb")
    assert usage["accounts"] == [
        {"code": "0012.10", "coordinate": "Synthetic!C9", "occurrences": 2}
    ]
    assert usage["control_groups"] == [{"code": "1XXX", "coordinate": "Synthetic!C8"}]
    journal = source_account_binding.observe_usage(
        workbook(journal_cells()), "Synthetic", "1c_journal"
    )
    assert {row["code"]: row["coordinate"] for row in journal["accounts"]} == {
        "0012.10": "Synthetic!K3",
        "1210": "Synthetic!Q3",
    }


@pytest.mark.parametrize(
    "change,message",
    [
        ({(2, 16): ""}, "missing an account"),
        ({(1, 10): "Account"}, "headers differ"),
        ({(3, 9): "Another company"}, "one unambiguous"),
        ({(3, 8): "orphan document"}, "one unambiguous"),
        ({(2, 10): (1.234, "0.00")}, "would round"),
        ({(2, 10): (1.2, "General")}, "requires explicit identity"),
        ({(2, 10): True}, "must be text"),
    ],
)
def test_account_usage_refuses_incomplete_or_guessed_identity(change, message):
    with pytest.raises(WorkspaceError, match=message):
        source_account_binding.observe_usage(
            workbook({**journal_cells(), **change}), "Synthetic", "1c_journal"
        )


def test_source_rows_preserve_leap_period_and_nonadditive_outline():
    content = workbook(tb_cells(), levels={7: 0, 8: 1, 9: 2, 10: 1, 11: 0})
    result = source_financial_facts.read_rows(content, "Synthetic", "1c_tb")
    rows = {r["row"]: r for r in result["rows"]}
    assert result["duplicate_account_rows"] == {"0012.10": [9, 11]}
    assert rows[8]["account_code"] == ""
    assert rows[8]["attributes"]["opening_debit"] == "-12.25"
    assert rows[9]["attributes"]["period_start"] == "2024-02-01"
    assert rows[9]["attributes"]["period_end"] == "2024-02-29"
    assert rows[10]["attributes"]["parent_source_row_key"] == "Synthetic!9"
    assert rows[10]["attributes"]["source_row_role"] == "ANALYTICAL_ROW"
    assert rows[12]["attributes"]["source_row_role"] == "UNRESOLVED_ROW"
    assert rows[9]["attributes"]["source_details"]["cells"]["C"] == {
        "type": xlrd.XL_CELL_TEXT,
        "value": "0012.10",
    }
    assert (
        rows[9]["attributes"]["source_details"]["aggregation_policy"]
        == "NON_ADDITIVE_REVIEW_REQUIRED"
    )
    rows[9]["attributes"]["turnover_debit"] = "tampered"
    assert (
        source_financial_facts.read_rows(content, "Synthetic", "1c_tb")["rows"][1]["attributes"][
            "turnover_debit"
        ]
        == "0.1"
    )
    annual = source_financial_facts.read_rows(
        workbook({**tb_cells(), (2, 2): "Период: 2024 \u0433."}), "Synthetic", "1c_tb"
    )
    assert annual["rows"][0]["attributes"]["period_end"] == "2024-12-31"


def test_journal_rows_keep_as_observed_amount_and_original_cell_coordinates():
    result = source_financial_facts.read_rows(workbook(journal_cells()), "Synthetic", "1c_journal")
    assert result["object_type"] == "SourceJournalMovement"
    row = result["rows"][0]
    assert row["debit_code"] == "0012.10" and row["credit_code"] == "1210"
    assert row["attributes"]["posting_date"] == "2024-02-29"
    assert row["attributes"]["amount"] == "-44.21"
    assert row["attributes"]["source_row_key"] == "Synthetic!3"
    assert row["attributes"]["unit_status"] == "UNESTABLISHED"
    assert row["attributes"]["source_details"]["cells"]["W"] == {
        "type": xlrd.XL_CELL_NUMBER,
        "value": "-44.21",
    }


@pytest.mark.parametrize(
    "change,message",
    [
        ({(2, 6): "not a date"}, "invalid source date"),
        ({(2, 3): 28}, "date fields disagree"),
        ({(2, 8): " "}, "document reference"),
        ({(2, 22): "44.21"}, "Numeric source amount"),
    ],
)
def test_journal_source_refuses_date_amount_and_reference_ambiguity(change, message):
    with pytest.raises(WorkspaceError, match=message):
        source_financial_facts.read_rows(
            workbook({**journal_cells(), **change}), "Synthetic", "1c_journal"
        )


@pytest.mark.parametrize(
    "change,message",
    [
        ({(6, 6): "Unknown amount"}, "measure headers changed"),
        ({(5, 6): "Unknown period position"}, "balance/movement headers changed"),
        ({(2, 2): "Unknown period"}, "supported accounting period"),
        ({(8, 10): "0.1"}, "Numeric source amount"),
    ],
)
def test_source_tb_refuses_unestablished_period_or_numeric_interpretation(change, message):
    with pytest.raises(WorkspaceError, match=message):
        source_financial_facts.read_rows(workbook({**tb_cells(), **change}), "Synthetic", "1c_tb")


@pytest.mark.parametrize(
    "cells,message",
    [
        ({(0, 2): "A"}, "not a recognized"),
        ({**tb_cells(), (1, 2): "Unknown title"}, "title is missing"),
        ({**tb_cells(), (0, 2): 123}, "company title"),
        ({**tb_cells(), (0, 2): " "}, "company title"),
    ],
)
def test_tb_company_requires_explicit_title_observation(cells, message):
    with pytest.raises(WorkspaceError, match=message):
        company_source.observe_tb_company(workbook(cells), "Synthetic")


def test_account_profile_must_be_known_and_amount_must_be_finite():
    with pytest.raises(WorkspaceError, match="Unknown account source profile"):
        source_account_binding.observe_usage(workbook(journal_cells()), "Synthetic", "unknown")
    for invalid in (float("inf"), float("nan")):
        with pytest.raises(WorkspaceError, match="not finite"):
            source_financial_facts.read_rows(
                workbook({**journal_cells(), (2, 22): invalid}), "Synthetic", "1c_journal"
            )


@pytest.mark.parametrize("operation", ["xls", "company", "accounts", "facts"])
def test_parser_releases_real_workbook_on_refused_interpretation(monkeypatch, operation):
    original = xlrd.open_workbook
    released = []

    def tracking_open(*args, **kwargs):
        book = original(*args, **kwargs)
        release = Mock(wraps=book.release_resources)
        book.release_resources = release
        released.append(release)
        return book

    monkeypatch.setattr(xlrd, "open_workbook", tracking_open)
    content = workbook({**tb_cells(), (6, 2): "Unknown account header"})
    with pytest.raises((ValueError, WorkspaceError)):
        if operation == "xls":
            inspect_xls(content)
        elif operation == "company":
            company_source.observe_companies(content, "Missing", 1, 1)
        elif operation == "accounts":
            source_account_binding.observe_usage(content, "Synthetic", "1c_tb")
        else:
            source_financial_facts.read_rows(
                workbook({**tb_cells(), (8, 10): "not an amount"}), "Synthetic", "1c_tb"
            )
    assert released
    assert all(release.call_count == 1 for release in released)

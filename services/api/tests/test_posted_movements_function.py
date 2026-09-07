from copy import deepcopy

import pytest
from test_seg_expense_source import workbook

from finai_api.services.posted_movements_function import calculate
from finai_api.services.seg_expense_source import read_base
from finai_api.services.workspace import WorkspaceError


def fixture():
    parsed = read_base(workbook())
    source = {
        "sha256": parsed["source_sha256"],
        "sheet": "Base",
        "row_count": 1,
        "context": {"currency_id": "GEL-id"},
        "observed_from": "2025-01-01",
        "observed_through": "2025-01-31",
        "accounts": {
            "0012.01": {"resource_id": "debit", "version_id": "d1"},
            "3110": {"resource_id": "credit", "version_id": "c1"},
        },
    }
    return parsed, source


def test_posted_amount_preserves_exact_value_and_drill_not_supplementary_or_vat():
    parsed, source = fixture()
    result = calculate(parsed, source)
    assert [group["value"] for group in result["groups"]] == ["731.97", "731.97"]
    assert [group["side"] for group in result["groups"]] == ["debit", "credit"]
    assert result["included_coordinates"] == ["Base!S2"]
    assert all(group["source_coordinates"] == ["Base!S2"] for group in result["groups"])
    assert result["coverage"]["ledger_completeness"] == "UNESTABLISHED"


@pytest.mark.parametrize("observation", [{}, {"literal_decimal": None, "cached_decimal": "999"}])
def test_missing_or_formula_amount_is_quarantined_never_zero(observation):
    parsed, source = fixture()
    parsed["rows"][0]["numeric_observations"]["source_amount"] = observation
    result = calculate(parsed, source)
    assert result["groups"] == []
    assert result["excluded_rows"] == [
        {"row": 2, "coordinate": "Base!S2", "reason": "MISSING_LITERAL_POSTED_AMOUNT"}
    ]
    assert result["coverage"]["included_rows"] == 0


@pytest.mark.parametrize(
    "change", ["hash", "duplicate", "account", "date", "coordinate", "exponent"]
)
def test_refuses_incompatible_or_unbounded_postings(change):
    parsed, source = fixture()
    row = parsed["rows"][0]
    if change == "hash":
        source["sha256"] = "changed"
    elif change == "duplicate":
        parsed["posting_identity_ready"] = False
    elif change == "account":
        row["attributes"]["account_code"] = "unmapped"
    elif change == "date":
        row["attributes"]["posting_date"] = "2026-01-01"
    elif change == "coordinate":
        row["numeric_observations"]["source_amount"]["coordinate"] = "Base!AD2"
    else:
        row["numeric_observations"]["source_amount"]["literal_decimal"] = "1e999999"
    with pytest.raises(WorkspaceError):
        calculate(parsed, source)


def test_exact_decimal_sum_preserves_small_increment_without_float_rounding():
    parsed, source = fixture()
    row = deepcopy(parsed["rows"][0])
    row["row"] = 3
    row["attributes"]["source_row_key"] = "Base!3"
    row["numeric_observations"]["source_amount"].update(
        coordinate="Base!S3", literal_decimal="0.0000000000000001"
    )
    parsed["rows"].append(row)
    source["row_count"] = 2
    result = calculate(parsed, source)
    assert [group["value"] for group in result["groups"]] == [
        "731.9700000000000001",
        "731.9700000000000001",
    ]

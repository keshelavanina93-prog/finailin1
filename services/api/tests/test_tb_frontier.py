from copy import deepcopy

from finai_api.services.tb_frontier import MEASURES, analyze


def sample():
    def row(index, code, role, level, parent, amount):
        return {
            "source_row": index,
            "values": {
                "source_account_code": code,
                "source_row_role": role,
                "source_account_name": "Account" if code else "",
                "source_analytic_label": "Detail" if role == "ANALYTICAL_ROW" else "",
                "source_outline_level": str(level),
                "hierarchy_parent_row": str(parent or ""),
                **{m: amount for m in MEASURES},
            },
        }

    return [
        row(8, "11XX", "ACCOUNT_GROUP", 0, None, "-10.25"),
        row(9, "1110", "ACCOUNT_SUMMARY", 1, 8, "-10.25"),
        row(10, "", "ANALYTICAL_ROW", 2, 9, "-10.25"),
        row(11, "", "UNRESOLVED_ROW", 0, None, "-10.25"),
    ]


def test_frontier_excludes_overlapping_details_and_preserves_signed_amounts():
    proof = analyze(sample())
    assert proof["state"] == "RECONCILED_CANDIDATE"
    assert proof["selected_rows"] == [8]
    assert proof["account_totals"]["closing_debit"] == "-10.25"
    assert proof["naive_sum_overstatement"]["closing_debit"] == "-20.50"
    assert proof["authority_state"] == "MAPPED_CANDIDATE"
    assert proof["account_depth_available"] is False


def test_mismatched_total_or_invalid_numeric_never_reconciles():
    changed = deepcopy(sample())
    changed[-1]["values"]["closing_debit"] = "-11.25"
    assert analyze(changed)["state"] == "REVIEW_REQUIRED"
    changed[1]["values"]["opening_debit"] = "NaN"
    assert analyze(changed)["errors"] == [{"row": 9, "code": "INVALID_AMOUNT"}]

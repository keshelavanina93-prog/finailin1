from finai_api.services.source_accounting_reconciliation import reconcile_structure


def test_repeated_account_and_incomplete_outline_do_not_choose_financial_authority():
    def row(number, code, parent, **measures):
        attrs = {"source_row_key": f"TB!{number}", "source_row_role": "ACCOUNT_SUMMARY", **measures}
        if parent:
            attrs["parent_source_row_key"] = f"TB!{parent}"
        return {"row": number, "account_code": code, "attributes": attrs}

    result = reconcile_structure(
        {
            "object_type": "SourceTrialBalanceRow",
            "rows": [
                row(1, "7410", None, turnover_debit="0.3", closing_debit="0.3"),
                row(2, "7410", 1, turnover_debit="0.1", closing_debit="0.1"),
                row(3, "7410.01", 1, turnover_debit="0.2"),
            ],
        }
    )
    measures = {c["measure"]: c for c in result["hierarchy_measure_comparisons"]}
    assert measures["turnover_debit"]["state"] == "OBSERVED_AGREEMENT"
    assert measures["turnover_debit"]["difference"] == "0.0"
    assert measures["closing_debit"]["state"] == "INCOMPLETE"
    assert measures["closing_debit"]["children_value"] is None
    assert measures["closing_debit"]["missing_child_rows"] == ["TB!3"]
    pair = result["repeated_accounts"][0]["comparisons"][0]
    assert pair["outline_relation"] == "ANCESTOR_DESCENDANT"
    assert pair["measure_state"] == "DIFFERENT_OBSERVED_MEASURES"
    assert result["financial_certification"] is None
    assert result["state"] == "REVIEW_REQUIRED"

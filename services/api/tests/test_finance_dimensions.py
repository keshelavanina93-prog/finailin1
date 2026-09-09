from finai_api.domain.finance_dimensions import DimensionValidationRequest, validate


def test_account_family_order_is_explicit_and_unknown_until_reviewed():
    result = validate(
        DimensionValidationRequest(
            account_code="7410.99",
            bindings={"department": "ADMIN", "cost_article": None},
        )
    )
    assert result["state"] == "OBSERVED_LABEL_ONLY"
    assert result["observed_slot_order"] == ["department", "cost_article"]
    assert result["missing_dimensions"] == ["cost_article"]


def test_unmatched_account_family_is_an_explicit_unknown():
    result = validate(DimensionValidationRequest(account_code="9999"))
    assert result["state"] == "UNKNOWN"
    assert result["matched_policy"] is None


def test_rule_evidenced_family_requires_complete_dimensions():
    result = validate(
        DimensionValidationRequest(
            account_code="7310.02.1",
            bindings={"cost_article": "FUEL", "department": "OPS"},
            evidence_state="RULE_EVIDENCED",
        )
    )
    assert result["state"] == "RULE_EVIDENCED"
    assert result["missing_dimensions"] == []

from copy import deepcopy
from uuid import uuid4

import pytest
from test_posted_movements_function import fixture as source_fixture
from test_source_accounting_context import context

from finai_api.services.entity_movement_review import digest, review
from finai_api.services.workspace import WorkspaceError


def fixture():
    parsed, source = source_fixture()
    item, targets, ids = context()
    binding_id = str(uuid4())
    config = item.attributes
    config.update(
        amount_field="source_amount",
        amount_semantics="DEBIT_CREDIT",
        vat_treatment="AS_POSTED",
        supplementary_amount_field="annotated_amount",
        supplementary_amount_role="NON_AUTHORITATIVE_SOURCE_OBSERVATION",
    )
    targets[ids["scope"]]["attributes"].update(
        source_profile="seg_expense_base", observed_from="2025-01-01", observed_through="2025-01-31"
    )
    targets[ids["period"]]["attributes"].update(starts_on="2025-01-01", ends_on="2025-01-31")
    targets[ids["period"]]["object_type"] = "FiscalPeriod"
    targets[binding_id] = {
        "resource_id": binding_id,
        "version_id": str(uuid4()),
        "object_type": "SourceAccountingBinding",
        "attributes": config,
    }
    source.update(
        binding={"resource_id": binding_id},
        scope={"resource_id": ids["scope"]},
        company_id=ids["company"],
        context={
            k: config[k]
            for k in (
                "ledger_id",
                "book_id",
                "period_id",
                "currency_id",
                "functional_currency_id",
                "amount_field",
                "amount_semantics",
                "vat_treatment",
            )
        },
    )
    for code, ref in source["accounts"].items():
        targets[ref["resource_id"]] = {
            "resource_id": ref["resource_id"],
            "version_id": ref["version_id"],
            "object_type": "LocalAccount",
            "attributes": {"account_code": code, "chart_id": ids["chart"]},
        }
    return parsed, source, targets, ids


def test_reconciliation_and_source_pairs_do_not_claim_accepted_journals():
    parsed, source, targets, _ = fixture()
    original = deepcopy(parsed)
    result = review(parsed, source, targets, {})
    receipt = result["reconciliation"]
    assert (
        receipt["source_amount_total"]
        == receipt["source_pair_debit_total"]
        == receipt["source_pair_credit_total"]
        == "731.97"
    )
    assert (
        receipt["journal_debit_total"] is None
        and receipt["canonical_journal_trial_balance"] is None
    )
    assert receipt["accepted_canonical_journal_count"] == 0
    assert {issue["code"] for issue in result["pairs"][0]["promotion_blockers"]} == {
        "JOURNAL_PUBLICATION_CONTEXT_UNAVAILABLE",
        "ACCOUNT_DIMENSION_POLICY_UNESTABLISHED",
    }
    assert all(
        m["opening_balance"] is None and m["closing_balance"] is None for m in result["movements"]
    )
    assert [m["net_movement"] for m in result["movements"]] == ["731.97", "-731.97"]
    assert receipt["receipt_hash"] == digest(
        {k: v for k, v in receipt.items() if k != "receipt_hash"}
    )
    assert parsed == original


def test_s288_remains_missing_without_amount_substitution():
    parsed, source, targets, _ = fixture()
    parsed["rows"][0]["row"] = 288
    parsed["rows"][0]["numeric_observations"]["source_amount"] = {}
    parsed["rows"][0]["numeric_observations"]["annotated_amount"] = {"literal_decimal": "999"}
    result = review(parsed, source, targets, {})
    assert result["pairs"] == [] and result["movements"] == []
    assert result["reconciliation"]["excluded_rows"] == [
        {"row": 288, "coordinate": "Base!S288", "reason": "MISSING_LITERAL_POSTED_AMOUNT"}
    ]
    assert result["coverage"]["included_rows"] == 0


@pytest.mark.parametrize("amount", ["0.0000000000006576", "-1.01", "0"])
def test_unsupported_canonical_precision_or_sign_is_preserved_and_blocked(amount):
    parsed, source, targets, _ = fixture()
    parsed["rows"][0]["numeric_observations"]["source_amount"]["literal_decimal"] = amount
    result = review(parsed, source, targets, {})
    assert result["pairs"][0]["lines"][0]["amount"]["amount"] == amount
    assert any(
        i["code"] == "CANONICAL_JOURNAL_AMOUNT_CONTRACT_UNSUPPORTED"
        for i in result["pairs"][0]["promotion_blockers"]
    )


@pytest.mark.parametrize(
    "change", ["company", "book", "currency", "period", "chart", "version", "duplicate", "date"]
)
def test_wrong_context_or_identity_refused(change):
    parsed, source, targets, ids = fixture()
    if change == "company":
        targets[ids["ledger"]]["attributes"]["legal_entity_id"] = str(uuid4())
    elif change == "book":
        targets[ids["book"]]["attributes"]["ledger_id"] = str(uuid4())
    elif change == "currency":
        targets[ids["ledger"]]["attributes"]["currency_id"] = str(uuid4())
    elif change == "period":
        targets[ids["period"]]["attributes"]["ends_on"] = "2024-12-31"
    elif change == "chart":
        targets["debit"]["attributes"]["chart_id"] = str(uuid4())
    elif change == "version":
        targets["debit"]["version_id"] = str(uuid4())
    elif change == "date":
        parsed["rows"][0]["attributes"]["posting_date"] = "2025-02-01"
    else:
        other = deepcopy(parsed["rows"][0])
        other["row"] = 3
        other["numeric_observations"]["source_amount"]["coordinate"] = "Base!S3"
        parsed["rows"].append(other)
        source["row_count"] = 2
    with pytest.raises(WorkspaceError):
        review(parsed, source, targets, {})


def test_existing_policy_alone_never_approves_unreviewed_side_assignments():
    parsed, source, targets, _ = fixture()
    result = review(
        parsed,
        source,
        targets,
        {"debit": [{"resource_id": str(uuid4()), "version_id": str(uuid4())}]},
    )
    assert result["reconciliation"]["accepted_canonical_journal_count"] == 0
    assert any(
        i["code"] == "JOURNAL_DIMENSION_ASSIGNMENTS_REQUIRE_PUBLICATION_VALIDATION"
        for i in result["pairs"][0]["promotion_blockers"]
    )

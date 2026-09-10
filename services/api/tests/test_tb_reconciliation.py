from finai_api.services.tb_reconciliation import summarize_receipts


def _row(receipt_id, period, source_hash, source_use="ACTUAL_INPUT", working="2026-08"):
    return {
        "receipt_id": receipt_id,
        "source_sha256": source_hash,
        "request": {"source_use": source_use, "scope": {"period": working}},
        "receipt": {"observed_bindings": {"period": period}},
    }


def test_reconciliation_groups_same_content_without_mutation():
    result = summarize_receipts(
        [
            _row("ir-z", "2025-01", "a" * 64, "HISTORICAL_REFERENCE"),
            _row("ir-a", "2025-01", "a" * 64, "ACTUAL_INPUT"),
            _row("ir-b", "2025-02", "b" * 64),
        ]
    )

    assert result["mutation"] == "NONE"
    assert result["observed_periods"] == ["2025-01", "2025-02"]
    assert result["duplicate_group_count"] == 1
    first = result["groups"][0]
    assert first["receipt_ids"] == ["ir-a", "ir-z"]
    assert first["deterministic_candidate_receipt_id"] == "ir-a"
    assert first["status"] == "DUPLICATE_CONTENT_REVIEW_REQUIRED"


def test_reconciliation_keeps_working_period_as_context_only():
    result = summarize_receipts([_row("ir-a", "2025-01", "a" * 64)])

    assert result["period_authority"] == "SOURCE_INTERNAL_HEADER"
    assert result["groups"][0]["working_periods"] == ["2026-08"]


def test_reconciliation_prefers_a_readable_inline_source_candidate():
    rows = [
        {**_row("external", "2025-01", "a" * 64), "external_storage": True},
        {**_row("inline", "2025-01", "a" * 64), "inline_storage": True},
    ]

    result = summarize_receipts(rows)
    group = result["groups"][0]
    assert group["deterministic_candidate_receipt_id"] == "inline"
    assert group["inline_source_count"] == 1

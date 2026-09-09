"""Reconcile duplicate retained TB uploads without choosing accounting authority."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.review import Principal
from finai_api.storage import connection


def summarize_receipts(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Group retained trial-balance receipts by observed period and content hash.

    The returned canonical candidate is deterministic and review-only.  This
    function never deletes, rewrites, or approves a receipt; consumers still
    select one receipt per observed period before producing a draft.
    """

    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        receipt = row.get("receipt") or {}
        observed = (
            receipt.get("observed_bindings", {}).get("period") or row.get("observed_period") or ""
        )
        source_hash = str(row.get("source_sha256") or "")
        if observed and source_hash:
            groups[(str(observed), source_hash)].append(row)

    result_groups: list[dict[str, Any]] = []
    for (period, source_hash), members in sorted(groups.items()):
        ordered = sorted(members, key=lambda row: str(row.get("receipt_id", "")))
        actual = [
            row
            for row in ordered
            if (row.get("request") or {}).get("source_use", "ACTUAL_INPUT") == "ACTUAL_INPUT"
        ]
        selected = (actual or ordered)[0]
        working_periods = sorted(
            {
                str((row.get("request") or {}).get("scope", {}).get("period"))
                for row in ordered
                if (row.get("request") or {}).get("scope", {}).get("period")
            }
        )
        result_groups.append(
            {
                "observed_period": period,
                "source_sha256": source_hash,
                "receipt_ids": [str(row.get("receipt_id")) for row in ordered],
                "source_uses": [
                    (row.get("request") or {}).get("source_use", "ACTUAL_INPUT") for row in ordered
                ],
                "working_periods": working_periods,
                "duplicate_count": len(ordered),
                "status": "DUPLICATE_CONTENT_REVIEW_REQUIRED"
                if len(ordered) > 1
                else "SINGLE_RETAINED_CONTENT",
                "deterministic_candidate_receipt_id": str(selected.get("receipt_id")),
                "selection_policy": (
                    "PREFER_ACTUAL_INPUT_THEN_LEXICOGRAPHIC_RECEIPT_ID; REVIEW_REQUIRED_NO_MUTATION"
                ),
            }
        )
    periods = sorted({group["observed_period"] for group in result_groups})
    return {
        "contract": "tb-receipt-reconciliation/1",
        "period_authority": "SOURCE_INTERNAL_HEADER",
        "mutation": "NONE",
        "observed_periods": periods,
        "groups": result_groups,
        "duplicate_group_count": sum(group["duplicate_count"] > 1 for group in result_groups),
        "receipt_count": sum(group["duplicate_count"] for group in result_groups),
        "review_state": "REVIEW_REQUIRED",
    }


def reconcile_retained_tb(principal: Principal) -> dict[str, Any]:
    """Read all exact-scope TB receipts and return the review-only grouping."""

    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT receipt_id, request, receipt, source_sha256, submitted_by, ingested_at "
            "FROM hydration_runs WHERE tenant_id=%s AND exact_scope=%s "
            "AND receipt->>'source_class'='TRIAL_BALANCE' "
            "ORDER BY ingested_at, receipt_id LIMIT 100",
            (principal.scope.tenant_id, Jsonb(scope)),
        ).fetchall()
    result = summarize_receipts(rows)
    result["tenant_id"] = str(principal.scope.tenant_id)
    result["exact_scope"] = scope
    return result

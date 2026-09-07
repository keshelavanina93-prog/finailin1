"""Read-only authentic kernel proof; never publishes or self-certifies a journal.

Reads a retained posted Function invocation and exact source bytes. The candidate
compiler runs locally; this is not a newly published Function or live API proof.
"""

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from finai_api.domain.review import Principal
from finai_api.services import function_invocations, resources
from finai_api.services.accounting_source_document import read_source
from finai_api.services.entity_movement_review import digest, review
from finai_api.services.seg_expense_source import read_base
from finai_api.services.semantic_analysis_support import Resolver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invocation", required=True, type=UUID)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output).resolve()
    assert destination.drive.upper() == "D:"
    os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on"
    principal = next(
        Principal.model_validate(value)
        for value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
        if "ingest" in value["permissions"]
        and "ontology_admin" not in value["permissions"]
    )
    history = function_invocations.history(principal, args.invocation)
    assert history["status"] == "SUCCEEDED"
    with function_invocations._database(principal) as cursor:
        row = cursor.execute(
            "SELECT plan FROM function_invocations WHERE tenant_id=%s AND request_id=%s",
            (principal.scope.tenant_id, args.invocation),
        ).fetchone()
    assert row
    plan = row["plan"]
    source = plan["source_document"]
    assert source["company_id"] == "365aa5d9-c2ec-52e1-867a-50fe3415f486"
    metadata, content = read_source(principal, source["document_id"])
    assert metadata["source_sha256"] == source["sha256"]
    parsed = read_base(content, source["sheet"])
    resolver = Resolver(principal, plan)
    with resolver.read_session():
        targets = {
            ref["resource_id"]: resolver.version(ref)
            for ref in plan["static_dependencies"]
        }
    policies = resources.list_resources(
        principal, "AccountDimensionPolicy", "", 0, limit=1000
    )
    matching = {
        ref["resource_id"]: [
            p.model_dump(mode="json")
            for p in policies
            if p.attributes.get("account_id") == ref["resource_id"]
            and p.attributes.get("legal_entity_id") == source["company_id"]
            and p.authority_state == "APPROVED"
        ]
        for ref in source["accounts"].values()
    }
    result = review(parsed, source, targets, matching)
    assert result == review(parsed, source, targets, matching), (
        "Deterministic replay differs"
    )
    assert result["coverage"]["source_rows"] == 596 and len(result["pairs"]) == 595
    receipt = result["reconciliation"]
    assert receipt["source_amount_total"] == "12502967.2300000000006576"
    assert (
        receipt["source_pair_debit_total"]
        == receipt["source_pair_credit_total"]
        == receipt["source_amount_total"]
    )
    assert receipt["excluded_rows"] == [
        {
            "row": 288,
            "coordinate": "Base!S288",
            "reason": "MISSING_LITERAL_POSTED_AMOUNT",
        }
    ]
    assert (
        receipt["accepted_canonical_journal_count"] == 0
        and receipt["canonical_journal_trial_balance"] is None
    )
    original_totals = {
        (g["account_code"], g["side"]): g["value"]
        for g in history["output"]["posted_movements"]["groups"]
    }
    from decimal import Decimal

    for movement in result["movements"]:
        for side in ("debit", "credit"):
            assert Decimal(movement[side]) == Decimal(
                original_totals.get((movement["account_code"], side), "0")
            )
    excluded = next(r for r in parsed["rows"] if r["row"] == 288)
    evidence = {
        "state": "AUTHENTIC_READ_ONLY_KERNEL_PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "input_invocation": str(args.invocation),
        "input_receipt_hash": history["receipt_hash"],
        "input_run_id": history["output"]["run_id"],
        "source_sha256": source["sha256"],
        "reconciliation": receipt,
        "movement_accounts": len(result["movements"]),
        "movements": result["movements"],
        "pair_count": len(result["pairs"]),
        "pair_content_sha256": digest(result["pairs"]),
        "example_source_pair": result["pairs"][0],
        "blocker_occurrences": dict(
            Counter(
                issue["code"]
                for p in result["pairs"]
                for issue in p["promotion_blockers"]
            )
        ),
        "excluded_original_row": excluded,
        "native_writes_performed": False,
        "accepted_journal_trial_balance": False,
        "new_function_runtime_verified": False,
        "browser_acceptance": False,
        "independent_acceptance": False,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: evidence[k]
                for k in (
                    "state",
                    "movement_accounts",
                    "pair_count",
                    "blocker_occurrences",
                )
            }
        )
    )


if __name__ == "__main__":
    main()

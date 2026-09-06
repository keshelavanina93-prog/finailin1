"""Read-only proof of the retained, policy-filtered proposal queue through G8."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx


def main():
    token = next(
        key
        for key, grant in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in grant.get("permissions", [])
    )
    with httpx.Client(
        base_url="http://127.0.0.1:3062",
        timeout=15,
        headers={"Authorization": "Bearer " + token},
    ) as client:
        started = monotonic()
        response = client.get("/api/ontology/proposals")
        seconds = round(monotonic() - started, 3)
        response.raise_for_status()
        rows = response.json()
    assert isinstance(rows, list) and len(rows) <= 100
    required = {
        "proposal_id",
        "title",
        "rationale",
        "submitted_by",
        "created_at",
        "access_entity",
        "decision",
    }
    assert all(required <= row.keys() for row in rows)
    assert len({row["proposal_id"] for row in rows}) == len(rows)
    assert rows == sorted(
        rows,
        key=lambda row: (
            -datetime.fromisoformat(row["created_at"]).timestamp(),
            row["proposal_id"],
        ),
    )
    decisions = {}
    for row in rows:
        decisions[row["decision"]] = decisions.get(row["decision"], 0) + 1
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "capability": "NIN-25 / NIN-28 retained proposal queue",
        "mode": "authenticated running web proxy; read-only retained records",
        "http_status": response.status_code,
        "seconds": seconds,
        "rows": len(rows),
        "decision_counts": decisions,
        "stable_recency_order": True,
        "response_fields_preserved": True,
        "implementation": {
            "page_before_decision_join": True,
            "existing_recency_index": "resource_proposal_recency",
            "planner_preference": "transaction-local enable_sort=off",
            "reason": "RLS cardinality underestimation selected a full policy scan before LIMIT",
            "statement_budget_ms": 10000,
            "timeout_behavior": "409 without a partial queue",
            "rls_unchanged": True,
        },
        "native_verification": "test_proposal_list.py: varied limits, decisions, isolation, empty tenant",
        "browser_acceptance": False,
        "full_NIN_28_acceptance": False,
        "scale_acceptance": False,
        "release_accepted": False,
    }
    Path("docs/development/evidence/nin25-proposal-queue.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()

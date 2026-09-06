"""Read-only authentic G8 proposal pagination proof, including work beyond row 100."""

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
    params = {"limit": 25}
    seen = []
    observations = []
    snapshot = None
    with httpx.Client(
        base_url="http://127.0.0.1:3062",
        timeout=15,
        headers={"Authorization": "Bearer " + token},
    ) as client:
        for number in range(1, 6):
            started = monotonic()
            response = client.get("/api/ontology/proposal-queue", params=params)
            seconds = round(monotonic() - started, 3)
            response.raise_for_status()
            result = response.json()
            snapshot = snapshot or result["snapshot_at"]
            assert result["snapshot_at"] == snapshot
            assert result["decision_mode"] == "CURRENT_RETAINED_DECISION"
            assert result["limit"] == 25 and len(result["proposals"]) <= 25
            seen.extend(result["proposals"])
            assert len({row["proposal_id"] for row in seen}) == len(seen)
            assert seen == sorted(
                seen,
                key=lambda row: (
                    -datetime.fromisoformat(row["created_at"]).timestamp(),
                    row["proposal_id"],
                ),
            )
            assert all(
                datetime.fromisoformat(row["created_at"])
                <= datetime.fromisoformat(snapshot)
                for row in seen
            )
            observations.append(
                {
                    "page": number,
                    "seconds": seconds,
                    "http_status": response.status_code,
                    "rows": len(result["proposals"]),
                    "has_more": result["has_more"],
                }
            )
            cursor = result["next_cursor"]
            if not result["has_more"]:
                assert cursor is None
                break
            assert cursor == {
                key: result["proposals"][-1][key]
                for key in ("created_at", "proposal_id")
            }
            params = {
                "limit": 25,
                "snapshot_at": snapshot,
                "before_created_at": cursor["created_at"],
                "before_proposal_id": cursor["proposal_id"],
            }
    assert len(seen) > 100, (
        "Retained proof did not reach beyond the former 100-row ceiling"
    )
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "snapshot_at": snapshot,
        "mode": "authenticated read-only running G8 proxy over retained proposals",
        "observations": observations,
        "distinct_proposals": len(seen),
        "beyond_previous_100_row_ceiling": True,
        "ordered_without_duplicates": True,
        "decision_mode": "CURRENT_RETAINED_DECISION",
        "browser_acceptance": False,
        "full_NIN_28_acceptance": False,
        "release_accepted": False,
    }
    Path("docs/development/evidence/nin25-proposal-pages.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()

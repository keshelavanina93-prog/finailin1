"""Read-only live proof of typed company spatial snapshots; no telemetry is simulated."""

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
    cutoff = datetime.now(UTC).isoformat()
    observations = []
    with httpx.Client(
        base_url="http://127.0.0.1:3062",
        timeout=20,
        headers={"Authorization": "Bearer " + token},
    ) as client:
        for name, identity in (
            ("SOCAR Georgia Gas", "a5f221e2-17a1-5903-9f3f-e2d896b3fc9d"),
            ("SOCAR Georgia Petroleum", "dc706c30-a8fb-57dc-b098-8a6bf2c2309d"),
        ):
            for lens in ("enterprise_assets", "gas_network"):
                started = monotonic()
                response = client.get(
                    "/api/operations/map",
                    params={
                        "company_id": identity,
                        "lens": lens,
                        "valid_at": cutoff,
                        "known_at": cutoff,
                        "limit": 1,
                    },
                )
                seconds = round(monotonic() - started, 3)
                response.raise_for_status()
                result = response.json()
                assert result["lens"] == lens
                assert datetime.fromisoformat(
                    result["known_at"]
                ) == datetime.fromisoformat(cutoff)
                assert datetime.fromisoformat(
                    result["valid_at"]
                ) == datetime.fromisoformat(cutoff)
                assert (
                    result["completeness"]["snapshot_scope"] == "COMPANY_SPATIAL_TYPES"
                )
                assert len(result["features"]) <= 1 and len(result["unmapped"]) <= 1
                counts = result["counts"]
                assert counts["assets"] == sum(
                    counts[k]
                    for k in (
                        "mapped_in_bounds",
                        "outside_bounds",
                        "unmapped",
                    )
                )
                assert result["operational_state"]["telemetry"] == "NOT_CONNECTED"
                observations.append(
                    {
                        "company_id": identity,
                        "name": name,
                        "lens": lens,
                        "http_status": response.status_code,
                        "seconds": seconds,
                        "counts": counts,
                        "completeness": result["completeness"],
                        "operational_state": result["operational_state"],
                    }
                )
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "fixed_cutoff": cutoff,
        "capability": "NIN-25 existing Operations canonical spatial projection",
        "mode": "authenticated running web proxy over retained canonical company identities",
        "observations": observations,
        "interpretation": "Zero assets means no accepted spatial assets in this scoped snapshot",
        "browser_acceptance": False,
        "telemetry_acceptance": False,
        "full_NIN_36_acceptance": False,
        "release_accepted": False,
    }
    Path("docs/development/evidence/nin25-operations-snapshot.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()

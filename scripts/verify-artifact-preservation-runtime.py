"""Verify preservation assessment over an actual retained source; execute no disposition."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--receipt-id",
        default="ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/development/evidence/nin27-artifact-preservation-runtime.json"
        ),
    )
    args = parser.parse_args()
    token = next(
        key
        for key, grant in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if {"ontology_read", "ontology_admin"}.issubset(grant["permissions"])
    )
    artifact = {"kind": "SOURCE_RECEIPT", "receipt_id": args.receipt_id}
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology/retention",
        headers={"Authorization": "Bearer " + token},
        timeout=30,
    ) as client:
        initial = client.post("/inspect", json={"artifact": artifact})
        initial.raise_for_status()
        original = initial.json()
        assert original["artifact"]["artifact_class"] == "IMMUTABLE_SOURCE_EVIDENCE"
        assert original["execution_authorized"] is False
        results = []
        for action in ("PRESERVE", "DELETE"):
            request = {
                "request_id": str(
                    uuid5(NAMESPACE_URL, args.receipt_id + ":retention:" + action)
                ),
                "artifact": artifact,
                "requested_action": action,
            }
            response = client.post("/evaluations", json=request)
            response.raise_for_status()
            receipt = response.json()
            assert receipt["proof"]["artifact"] == original["artifact"]
            assert receipt["proof"]["status"] == (
                "PRESERVED" if action == "PRESERVE" else "BLOCKED"
            )
            assert receipt["proof"]["reasons"] == ["POLICY_NOT_ESTABLISHED"]
            assert receipt["execution_authorized"] is False
            assert receipt["proof"]["legal_compliance_established"] is False
            assert receipt["proof"]["effective_disposition"] == "PRESERVE"
            repeat = client.post("/evaluations", json=request)
            repeat.raise_for_status()
            assert repeat.json() == receipt
            reopened = client.get(f"/receipts/{receipt['evaluation_id']}")
            reopened.raise_for_status()
            assert reopened.json() == receipt
            results.append(receipt)
        final = client.post("/inspect", json={"artifact": artifact})
        final.raise_for_status()
        assert final.json() == original
    args.output.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "artifact": original["artifact"],
                "evaluations": results,
                "repeat_and_history_equal": True,
                "source_still_readable_and_hash_unchanged": True,
                "disposition_executed": False,
                "legal_compliance_established": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Real source preservation assessment retained; unconfigured deletion evaluation blocked; original unchanged."
    )


if __name__ == "__main__":
    main()

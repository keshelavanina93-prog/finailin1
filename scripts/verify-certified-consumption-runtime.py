"""Read back the synthetic native certification journey through deployed G8 APIs.

No source, company, financial authority or certification state is created here.
The native journey withdrew its policy; the retained receipt must remain readable
while current consumption status remains BLOCKED after runtime restart.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
from psycopg.rows import dict_row


def main() -> None:
    token = next(
        key
        for key, grant in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if {"ontology_read", "ontology_admin"}.issubset(grant["permissions"])
    )
    with psycopg.connect(
        os.environ["FINAI_MIGRATION_DATABASE_URL"], row_factory=dict_row
    ) as conn:
        row = conn.execute(
            "SELECT consumption_id,payload,proof_hash FROM guarded_consumption_receipts "
            "WHERE access_entity LIKE 'synthetic-certified-%%' "
            "AND payload->>'contract_version'='guarded-consumption/3' "
            "AND payload->>'minimum_state'='CERTIFIED' ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None, (
            "Run the focused native certified consumption journey first"
        )
    identity = str(row["consumption_id"])
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology",
        headers={"Authorization": "Bearer " + token},
        timeout=20,
    ) as client:
        response = client.get(f"/lifecycle/consumptions/{identity}")
        response.raise_for_status()
        history = response.json()
        assert history["proof"] == row["payload"]
        assert history["proof_hash"] == row["proof_hash"]
        assert history["current_use_authorized"] is False
        status_response = client.get(f"/lifecycle/consumptions/{identity}/status")
        status_response.raise_for_status()
        status = status_response.json()
        assert status["status"] == "BLOCKED"
        assert status["current_use_authorized"] is False
        assert status["legacy_proof_requires_recheck"] is False
        material = next(
            item for item in history["proof"]["inputs"] if item.get("certification")
        )
        certification_response = client.get(
            f"/certifications/receipts/{material['certification']['receipt_id']}"
        )
        certification_response.raise_for_status()
        receipt = certification_response.json()
        assert receipt["proof_hash"] == material["certification"]["proof_hash"]
        assert receipt["current_use_authorized"] is False
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "scope": "SYNTHETIC_DEFINITION_CERTIFICATION_RESTART_READBACK",
        "consumption_id": identity,
        "proof_hash": history["proof_hash"],
        "historical_readback_status": response.status_code,
        "current_status_response": status,
        "certification_receipt_id": receipt["receipt_id"],
        "retained_conformance_proof_hash": receipt["proof_hash"],
        "historical_proof_matches_database": True,
        "financial_or_authentic_source_certification": False,
        "browser_or_release_acceptance": False,
    }
    Path(
        "docs/development/evidence/nin27-certified-consumption-runtime.json"
    ).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        "Retained synthetic certification proof survived; withdrawn policy blocks current use."
    )


if __name__ == "__main__":
    main()

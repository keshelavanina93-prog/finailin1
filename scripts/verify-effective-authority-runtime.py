"""Read-only deployed migration/lifecycle smoke proof; no financial authority claim."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn:
        assert conn.execute("SELECT 1 FROM schema_migrations WHERE version=32").fetchone()
    company = "a5f221e2-17a1-5903-9f3f-e2d896b3fc9d"
    version = "72417af7-1f6f-5d11-b6ff-607e96169191"
    with httpx.Client(
        base_url="http://127.0.0.1:3062",
        headers={"Authorization": "Bearer " + token},
        timeout=15,
    ) as client:
        response = client.get(
            f"/api/ontology/lifecycle/versions/{version}", params={"resource_id": company}
        )
        response.raise_for_status()
        result = response.json()
        assert result["subject"] == {"resource_id": company, "version_id": version}
        assert result["purpose"] == "HISTORICAL_LIFECYCLE"
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "migration": 32,
        "migration_applied": True,
        "web_api_lifecycle_status": response.status_code,
        "subject": result["subject"],
        "purpose": result["purpose"],
        "scope": "Read-only deployed lifecycle path using retained Gas company identity",
        "scheduled_version_acceptance": "See focused native test_resource_lifecycle.py proof",
        "financial_authority_or_release_acceptance": False,
    }
    Path("docs/development/evidence/nin27-effective-authority-runtime.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    print("Migration 32 and deployed web/API lifecycle read passed.")


if __name__ == "__main__":
    main()

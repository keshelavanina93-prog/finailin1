"""Read-only catalog-to-execution check for the retained source account Object Set."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    identity = "bbbe95f6-a0d0-4313-ab3e-6ebc73177087"
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology/model",
        headers={"Authorization": "Bearer " + token},
        timeout=20,
    ) as client:
        catalog = client.get("/definitions")
        catalog.raise_for_status()
        listed = next(row for row in catalog.json() if row["resource_id"] == identity)
        response = client.get(f"/sets/{identity}/objects", params={"limit": 5})
        response.raise_for_status()
        result = response.json()
        assert result["definition_id"] == identity
        assert result["definition_version_id"] == listed["version_id"]
        assert result["total"] > 0
        assert all(row["object_type"] == "SourceAccountDefinition" for row in result["objects"])
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "web_api_status": response.status_code,
        "definition_id": identity,
        "catalog_and_execution_version_id": result["definition_version_id"],
        "total": result["total"],
        "returned": len(result["objects"]),
        "query": result["query"],
        "scope": "Retained source account definitions; not activated ledger accounts",
        "future_scheduling_proof": "Separate native synthetic definition regression",
        "financial_authority_or_release_acceptance": False,
    }
    Path("docs/development/evidence/nin26-effective-definition-runtime.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    print("Retained source Object Set catalog and unpinned execution versions agree.")


if __name__ == "__main__":
    main()

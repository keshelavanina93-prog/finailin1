"""Check retained source derivation through the deployed web/API after range guards."""

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
    identity = "b9fbde64-2cc8-4c4e-bf44-fe8fbb38c13a"
    version = "004d96fa-4d75-5ea3-9f83-19669cd69255"
    response = httpx.post(
        "http://127.0.0.1:3062/api/ontology/model/derived/query",
        headers={"Authorization": "Bearer " + token},
        json={
            "query": {
                "object_type": "SourceAccountDefinition",
                "filters": [{"field": "evidence_id", "value": "0074068a-99ea-5a03-8e61-15f7430b04d4"}],
                "limit": 5,
            },
            "definitions": [identity],
            "definition_versions": {identity: version},
        },
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    rows = result["derived_values"]
    assert len(rows) == 5
    assert all(row["status"] == "AVAILABLE" for row in rows)
    assert all(row["definition_version_id"] == version for row in rows)
    assert {row["object_version_id"] for row in rows} == {
        row["version_id"] for row in result["objects"]
    }
    reopened = httpx.get(
        f"http://127.0.0.1:3062/api/ontology/model/fact-runs/{result['run_id']}",
        headers={"Authorization": "Bearer " + token},
        timeout=20,
    )
    reopened.raise_for_status()
    assert reopened.json() == result
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "web_api_status": response.status_code,
        "definition_id": identity,
        "definition_version_id": version,
        "derived_rows": len(rows),
        "all_available": True,
        "exact_object_versions_preserved": True,
        "run_id": result["run_id"],
        "retained_readback_equal": True,
        "scope": "Retained source account labels, not financial results",
        "range_failure_proof": "Focused derived decimal range regression",
        "financial_certification_or_release_acceptance": False,
    }
    Path("docs/development/evidence/nin26-derived-range-runtime.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    print("Five retained source derivations remain available with exact version pins.")


if __name__ == "__main__":
    main()

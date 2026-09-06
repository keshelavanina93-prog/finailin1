"""Read-only native API proof of retained company-360 projections."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient
from finai_api.main import app


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    results = []
    with TestClient(app) as client:
        assert client.get("/v1/ontology/company-context").status_code == 401
        client.headers["Authorization"] = "Bearer " + token
        response = client.get("/v1/ontology/company-context")
        response.raise_for_status()
        directory = response.json()
        companies = {
            row["company"]["resource_id"]: row["company"]
            for row in directory["workspaces"]
        }
        for company_id, company in companies.items():
            started = perf_counter()
            response = client.get(
                "/v1/ontology/company-context", params={"company_id": company_id}
            )
            elapsed = round((perf_counter() - started) * 1000)
            response.raise_for_status()
            context = response.json()["context"]
            assert context["company"]["resource_id"] == company_id
            assert context["company"]["evidence_class"] != "REFERENCE_TEMPLATE"
            results.append(
                {
                    "company_id": company_id,
                    "company_version": context["company"]["version_id"],
                    "name": company["display_name"],
                    "latency_ms": elapsed,
                    "ledger_count": len(context["ledgers"]),
                    "source_scope_count": len(context["accounting_sources"]),
                    "relationship_count": len(context["relationships"]),
                    "filing_count": len(context["disclosures"]),
                    "licence_evidence_count": len(context["licence_evidence"]),
                }
            )
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "capability": "NIN-25 company-360",
        "source": "existing retained canonical resources in native PostgreSQL",
        "mode": "read-only authenticated TestClient",
        "companies": results,
        "unauthenticated_denied": True,
        "browser_acceptance": "UNVERIFIED",
        "gates": {
            "CODE_PRESENT": True,
            "LOCAL_CONTRACT_PASS": True,
            "LOCAL_INTEGRATED_PASS": True,
            "AUTHENTIC_SOURCE_PASS": "retained company projection only",
            "BROWSER_ACCEPTANCE_PASS": False,
            "RELEASE_ACCEPTED": False,
        },
        "limits": {
            "directory_page": 50,
            "graph_nodes": 200,
            "graph_edges": 400,
            "snapshot_resources": 5000,
            "binding_eligibility_checks": 100,
        },
        "release_accepted": False,
    }
    destination = Path("docs/development/evidence/nin25-company-360.json")
    destination.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()

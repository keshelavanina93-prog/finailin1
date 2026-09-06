"""Verify retained regulatory evidence without activating legal or financial rules."""

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from finai_api.main import app


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    companies, publications = [], []
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        directory = client.get("/v1/ontology/company-context")
        directory.raise_for_status()
        for workspace in directory.json()["workspaces"]:
            company = workspace["company"]
            response = client.get(
                "/v1/ontology/regulation/rules",
                params={"legal_entity_id": company["resource_id"]},
            )
            response.raise_for_status()
            result = response.json()
            assert result["activity"] is None
            assert result["context_basis"] == "INCOMPLETE_CONTEXT"
            assert all(
                not row["assessment"]["effective_obligation"] for row in result["rules"]
            )
            companies.append(
                {
                    "company_id": company["resource_id"],
                    "context_basis": result["context_basis"],
                    "rules": [
                        {
                            "resource_id": row["resource"]["resource_id"],
                            "version_id": row["resource"]["version_id"],
                            "assessment": row["assessment"],
                            "dependencies": row["dependencies"],
                        }
                        for row in result["rules"]
                    ],
                }
            )
        response = client.get("/v1/ontology/regulation/sources")
        response.raise_for_status()
        for publication in response.json()["publications"]:
            document_id = publication["attributes"]["document_id"]
            response = client.get(
                "/v1/ontology/regulation/sources/inspect",
                params={"document_id": document_id},
            )
            response.raise_for_status()
            source = response.json()
            response = client.post(
                "/v1/ontology/regulation/sources/impact",
                json={"document_id": document_id},
            )
            response.raise_for_status()
            impact = response.json()
            assert (
                not impact["legal_change_verified"] and not impact["accounting_effects"]
            )
            assert impact["financial_impact"]["amount"] is None
            reopened = client.get("/v1/ontology/regulation/impacts/" + impact["run_id"])
            reopened.raise_for_status()
            assert reopened.json() == impact
            publications.append(
                {
                    "resource_id": publication["resource_id"],
                    "version_id": publication["version_id"],
                    "document": source["document"],
                    "completeness": source["observation"]["completeness"],
                    "retained_impact_id": impact["run_id"],
                    "impact_reopened_equal": True,
                    "affected_count": len(impact["dependency_impact"]["affected"]),
                    "legal_change_verified": False,
                    "accounting_effects": False,
                }
            )
    evidence = {
        "capability": "NIN-25 retained regulatory readiness and dependency investigation",
        "mode": "native authenticated API; retains potential dependency-impact evidence only",
        "companies": companies,
        "publications": publications,
        "browser_acceptance": False,
        "NIN_40_complete": False,
        "release_accepted": False,
    }
    Path("docs/development/evidence/nin25-regulatory-investigation.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"companies": len(companies), "publications": publications}))


if __name__ == "__main__":
    main()

"""Read-only retained company discovery and facet proof."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from finai_api.main import app


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    stamp = datetime.now(UTC).isoformat()
    rows = []
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token
        directory = client.get("/v1/ontology/company-context").json()
        for workspace in directory["workspaces"]:
            company = workspace["company"]
            params = {
                "company_id": company["resource_id"],
                "effective_at": stamp,
                "known_at": stamp,
                "limit": 1,
            }
            response = client.get("/v1/ontology/history-search", params=params)
            response.raise_for_status()
            result = response.json()
            assert result["matched_count"] == sum(
                facet["count"] for facet in result["type_facets"]
            )
            assert len(result["resources"]) <= 1
            for facet in result["type_facets"]:
                filtered = client.get(
                    "/v1/ontology/history-search",
                    params={**params, "object_type": facet["object_type"]},
                )
                filtered.raise_for_status()
                selection = filtered.json()
                assert selection["matched_count"] == facet["count"]
                assert selection["type_facets"] == result["type_facets"]
                assert all(
                    resource["object_type"] == facet["object_type"]
                    for resource in selection["resources"]
                )
            rows.append(
                {
                    "company_id": company["resource_id"],
                    "company_version": company["version_id"],
                    "name": company["display_name"],
                    "matched_count": result["matched_count"],
                    "type_facets": result["type_facets"],
                    "visible_page_size": len(result["resources"]),
                    "category_filters_verified": True,
                }
            )
    evidence = {
        "checked_at": stamp,
        "capability": "NIN-25 / NIN-35 company resource discovery",
        "mode": "authenticated native TestClient with retained canonical company resources",
        "companies": rows,
        "facets_before_type_and_pagination": True,
        "browser_acceptance": False,
        "NIN_42_completion": False,
        "release_accepted": False,
    }
    Path("docs/development/evidence/nin25-data-discovery.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()

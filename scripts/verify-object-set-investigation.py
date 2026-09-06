"""Read-only proof of retained query results and knowledge-bounded operator trace."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from finai_api.main import app


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    evidence = []
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        directory = client.get("/v1/ontology/company-context")
        directory.raise_for_status()
        for workspace in directory.json()["workspaces"]:
            company = workspace["company"]
            discovered = client.get(
                "/v1/ontology/history-search",
                params={"company_id": company["resource_id"], "limit": 1},
            )
            discovered.raise_for_status()
            resource = discovered.json()["resources"][0]
            query = {
                "object_type": resource["object_type"],
                "resource_ids": [resource["resource_id"]],
                "limit": 1,
            }
            result_response = client.post("/v1/ontology/object-sets/query", json=query)
            result_response.raise_for_status()
            result = result_response.json()
            assert result["total"] == 1
            exact = result["objects"][0]
            assert exact["version_id"] == resource["version_id"]
            replay = client.post("/v1/ontology/object-sets/query", json=result["query"])
            replay.raise_for_status()
            assert replay.json()["objects"] == result["objects"]
            path = f"/v1/ontology/operator/trace/{exact['resource_id']}"
            params = {
                "version_id": exact["version_id"],
                "known_at": result["query"]["known_at"],
            }
            response = client.get(path, params=params)
            response.raise_for_status()
            trace = response.json()
            assert trace["root_version_id"] == exact["version_id"]
            assert datetime.fromisoformat(trace["known_at"]) == datetime.fromisoformat(
                params["known_at"]
            )
            before = (
                datetime.fromisoformat(exact["system_from"]) - timedelta(microseconds=1)
            ).isoformat()
            unavailable = client.get(path, params={**params, "known_at": before})
            assert unavailable.status_code == 404
            evidence.append(
                {
                    "company_id": company["resource_id"],
                    "object_type": exact["object_type"],
                    "resource_id": exact["resource_id"],
                    "version_id": exact["version_id"],
                    "query": result["query"],
                    "replay_equal": True,
                    "trace_nodes": len(trace["nodes"]),
                    "trace_edges": len(trace["edges"]),
                    "knowledge_cutoff_verified": True,
                }
            )
    output = {
        "capability": "NIN-25 ontology result to exact-version investigation",
        "mode": "authenticated native API over retained company resources",
        "journeys": evidence,
        "browser_acceptance": False,
        "release_accepted": False,
    }
    Path("docs/development/evidence/nin25-object-set-investigation.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(output))


if __name__ == "__main__":
    main()

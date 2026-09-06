"""Verify server discovery beyond the loaded G8 graph, using retained resources."""

import json
import os
from pathlib import Path

import httpx


def main():
    token = next(
        key for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    with httpx.Client(base_url="http://127.0.0.1:3062/api/ontology/",
                      headers={"Authorization": "Bearer " + token}, timeout=25) as client:
        def get(path, **params):
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

        graph = get("graph")
        loaded_ids = {row["resource_id"] for row in graph["resources"]}
        companies = [w["company"]["resource_id"] for w in get("company-context")["workspaces"]]
        journeys = []
        for company in companies:
            first = get("history-search", company_id=company, limit=1)
            if not first["matched_count"]:
                continue
            context = dict(company_id=company, limit=1, known_at=first["known_at"], effective_at=first["effective_at"])
            last = get("history-search", **context, offset=first["matched_count"] - 1)
            target = last["resources"][0]
            found = get("history-search", **context, q=target["resource_id"].upper())
            assert found["matched_count"] == 1
            assert found["resources"][0]["version_id"] == target["version_id"]
            for other in companies:
                if other != company:
                    assert get("history-search", **{**context, "company_id": other}, q=target["resource_id"])["matched_count"] == 0
            journeys.append({
                "company_id": company, "company_resources": first["matched_count"],
                "resource_id": target["resource_id"], "version_id": target["version_id"],
                "known_at": first["known_at"], "exact_id_matches": found["matched_count"],
                "present_in_loaded_graph": target["resource_id"] in loaded_ids,
                "other_company_matches": 0,
            })
    assert journeys and any(not row["present_in_loaded_graph"] for row in journeys)
    evidence = {"live_web_api": "PASS", "loaded_graph_resources": len(loaded_ids),
                "retained_journeys": journeys, "browser_acceptance": False,
                "release_accepted": False}
    Path("docs/development/evidence/nin25-workspace-search.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()

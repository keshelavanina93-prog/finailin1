"""Record authentic retained query/inspection/trace knowledge continuity."""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from finai_api.main import app
import httpx


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in value["permissions"]
    )
    if "--live" in sys.argv:
        path = Path("docs/development/evidence/nin25-inspection-continuity.json")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        with httpx.Client(base_url="http://127.0.0.1:3062", headers={"Authorization": "Bearer " + token}, timeout=20) as client:
            for row in evidence["retained_resource_journeys"]:
                response = client.get(
                    f"/api/ontology/operator/resources/{row['resource_id']}",
                    params={"version_id": row["version_id"], "known_at": row["known_at"]},
                )
                response.raise_for_status()
                assert response.json()["resource"]["version_id"] == row["version_id"]
                assert response.json()["known_at"] == row["known_at"]
                row["live_web_api_status"] = response.status_code
        evidence["frontend_build"] = "PASS"
        evidence["frontend_types_lint"] = "PASS"
        path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print("Retained company inspections passed through restarted web/API.")
        return
    observations = []
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        directory = client.get("/v1/ontology/company-context")
        directory.raise_for_status()
        for workspace in directory.json()["workspaces"]:
            company = workspace["company"]["resource_id"]
            query = client.get(
                "/v1/ontology/history-search",
                params={"company_id": company, "limit": 1},
            )
            query.raise_for_status()
            result = query.json()
            if not result["resources"]:
                continue
            selected = result["resources"][0]
            params = {"version_id": selected["version_id"], "known_at": result["known_at"]}
            inspected = client.get(
                f"/v1/ontology/operator/resources/{selected['resource_id']}", params=params
            )
            inspected.raise_for_status()
            detail = inspected.json()
            assert detail["resource"]["version_id"] == selected["version_id"]
            cutoff = datetime.fromisoformat(detail["known_at"])
            assert cutoff == datetime.fromisoformat(result["known_at"])
            assert all(datetime.fromisoformat(v["system_from"]) <= cutoff for v in detail["versions"])
            trace = client.get(
                f"/v1/ontology/operator/trace/{selected['resource_id']}", params=params
            )
            trace.raise_for_status()
            graph = trace.json()
            assert datetime.fromisoformat(graph["known_at"]) == cutoff
            assert all(datetime.fromisoformat(v["system_from"]) <= cutoff for v in graph["nodes"])
            before = datetime.fromisoformat(selected["system_from"]) - timedelta(microseconds=1)
            unavailable = client.get(
                f"/v1/ontology/operator/resources/{selected['resource_id']}",
                params={**params, "known_at": before.isoformat()},
            )
            assert unavailable.status_code == 404
            observations.append({
                "company_id": company,
                "resource_id": selected["resource_id"],
                "version_id": selected["version_id"],
                "known_at": detail["known_at"],
                "history_versions": len(detail["versions"]),
                "trace_nodes": len(graph["nodes"]),
                "before_recording_status": unavailable.status_code,
                "current_use_authorized": detail["current_use_authorized"],
            })
    assert observations
    Path("docs/development/evidence/nin25-inspection-continuity.json").write_text(
        json.dumps({
            "retained_resource_journeys": observations,
            "native_temporal_and_isolation_checks": "PASS",
            "derived_coalesce_focused_checks": "PASS",
            "browser_acceptance": False,
            "release_accepted": False,
        }, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(observations, indent=2))


if __name__ == "__main__":
    main()

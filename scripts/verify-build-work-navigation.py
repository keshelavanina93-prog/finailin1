"""Verify retained build routing and reject legacy control without creating work."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx


def main() -> None:
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token = next(t for t, g in grants.items() if "ingest" in g["permissions"])
    reference = json.loads(
        Path("docs/development/evidence/nin32-worksheet-runtime.json").read_text(
            encoding="utf-8"
        )
    )
    request_id = reference["request"]["request_id"]
    workflow_id = "transformation:" + request_id
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api",
        headers={"Authorization": "Bearer " + token},
        timeout=30,
    ) as client:
        response = client.get(
            "/workspace/workflows/workbench", params={"include_unbound": "true"}
        )
        response.raise_for_status()
        item = next(
            i for i in response.json()["items"] if i["workflow_id"] == workflow_id
        )
        assert item["family"] == "build"
        assert item["company_id"] is None and item["company_binding"] == "UNBOUND"
        path = "/ontology/transformations/runs/" + request_id
        response = client.get(path)
        response.raise_for_status()
        before = response.json()
        assert before["workflow_id"] == workflow_id
        assert (
            before["request"]["compiled_plan"]["request"]
            == reference["result"]["request"]["compiled_plan"]["request"]
        )
        refused = client.post(
            "http://127.0.0.1:8062/v1/workspace/workflows/" + workflow_id + "/control",
            json={
                "command": "cancel",
                "reason": "Verify cross-family refusal",
                "idempotency_key": str(uuid4()),
            },
        )
        assert refused.status_code == 409, refused.text
        response = client.get(path)
        response.raise_for_status()
        after = response.json()
        for key in ("request", "events", "publications"):
            assert before[key] == after[key] == reference["result"][key]
    Path("docs/development/evidence/nin29-build-work-navigation.json").write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "work_item": item,
                "request_id": request_id,
                "legacy_control_status": refused.status_code,
                "legacy_control_detail": refused.json(),
                "retained_evidence_unchanged": True,
                "created_work": False,
                "financial_authority_established": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Exact retained build resolved; legacy control refused; original evidence unchanged."
    )


if __name__ == "__main__":
    main()

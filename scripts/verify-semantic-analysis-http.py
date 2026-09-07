"""Read-only authenticated proof of the integrated semantic workspace API."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--api", default="http://127.0.0.1:8062")
parser.add_argument("--metadata-invocation")
parser.add_argument("--output", required=True)
args = parser.parse_args()
destination = Path(args.output).resolve()
assert destination.drive.upper() == "D:", "Evidence must stay on D:"
grant = next(
    (token, value)
    for token, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
    if "ingest" in value["permissions"]
)
timings = []


def call(path, body=None, authenticated=True):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = "Bearer " + grant[0]
    request = Request(
        args.api + "/v1/ontology/" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    started = perf_counter()
    try:
        with urlopen(request, timeout=45) as response:
            status, data = response.status, json.load(response)
    except HTTPError as exc:
        status, data = exc.code, json.load(exc)
    timings.append(
        {"path": path, "status": status, "seconds": round(perf_counter() - started, 3)}
    )
    return status, data


posted_id = "c631bb9c-f92e-5dd9-a693-233c1b3b7925"
posted_company = "365aa5d9-c2ec-52e1-867a-50fe3415f486"
base = {"invocation_id": posted_id, "company_id": posted_company}
status, result = call("analysis/project", base)
assert status == 200, (status, result)
descriptor = result["descriptor"]
assert len(result["rows"]) == 59
assert (
    descriptor["receipt_hash"]
    == "1cb82d90e0945947feb5aee646d8dc3ce076a4c2311b4b2eea17a41dfe2350d7"
)
assert descriptor["excluded_evidence"][0]["coordinate"] == "Base!S288"
selected = next(
    row
    for row in result["rows"]
    if row["values"]["side"]["value"] == "debit"
    and row["values"]["account"]["label"].startswith("7310.02.1")
)
assert selected["values"]["posted_amount"]["value"] == "58988.95"
revision = result["descriptor_sha256"]
selection = {
    **base,
    "descriptor_sha256": revision,
    "selected_row": selected["key"],
    "group_by": "side",
    "filters": [{"field": "side", "value": "debit"}],
    "contributor_index": 0,
}
status, detail = call("analysis/project", selection)
assert status == 200, (status, detail)
assert detail["descriptor_sha256"] == revision
assert all(row["values"]["side"]["value"] == "debit" for row in detail["rows"])
assert detail["selection"]["contributor_count"] == 6
cell = next(
    cell
    for cell in detail["selection"]["contributor"]["cells"]
    if cell["coordinate"] == "Base!S2"
)
assert cell["value"] == "731.97"
assert call("analysis/project", base, authenticated=False)[0] == 401
assert call("analysis/project", {**base, "aggregation": "sum"})[0] == 422
assert call("analysis/project", {**base, "descriptor_sha256": "0" * 64})[0] == 409
assert (
    call(
        "analysis/project",
        {**base, "company_id": "c6f87828-9609-5b35-afa6-e894a0acfe41"},
    )[0]
    == 404
)
status, original = call("functions/invocations/" + posted_id)
assert status == 200 and original["receipt_hash"] == descriptor["receipt_hash"]
assert original["output"]["run_id"] == descriptor["run_id"]
metadata = None
if args.metadata_invocation:
    metadata_request = {
        "invocation_id": args.metadata_invocation,
        "company_id": "c6f87828-9609-5b35-afa6-e894a0acfe41",
    }
    status, subject = call("analysis/project", metadata_request)
    assert status == 200, (status, subject)
    assert len(subject["rows"]) == 3
    assert subject["descriptor"]["grain"] == ["source_header"]
    assert {row["values"]["source_header"]["value"] for row in subject["rows"]} == {
        "Department",
        "Region",
        "Budget Article New",
    }
    assert all(
        row["values"]["observation_count"]["value"] == 1 for row in subject["rows"]
    )
    cells = []
    for row in subject["rows"]:
        status, selected_subject = call(
            "analysis/project",
            {
                **metadata_request,
                "descriptor_sha256": subject["descriptor_sha256"],
                "selected_row": row["key"],
            },
        )
        assert status == 200, (status, selected_subject)
        contributor = selected_subject["selection"]["contributor"]
        assert (
            contributor["document_id"]
            == "doc_dc27fd0f86d1a1bec33e56fc2deb01ff97390c85e52c5fabab59a32ad978b627"
        )
        assert len(contributor["cells"]) == 1
        assert (
            contributor["cells"][0]["value"] == row["values"]["source_header"]["value"]
        )
        cells += contributor["cells"]
    assert {cell["coordinate"] for cell in cells} == {"TR!Y2", "TR!Z2", "TR!AA2"}
    metadata = {
        "invocation_id": args.metadata_invocation,
        "descriptor_sha256": subject["descriptor_sha256"],
        "receipt_hash": subject["descriptor"]["receipt_hash"],
        "run_id": subject["descriptor"]["run_id"],
        "function": subject["descriptor"]["function"],
        "original_cells": cells,
        "non_posting_source_metadata": True,
        "financial_authority": False,
    }
evidence = {
    "state": "LOCAL_INTEGRATED_HTTP_PASS",
    "recorded_at": datetime.now(UTC).isoformat(),
    "api": args.api,
    "writes_performed": False,
    "posted": {
        "invocation_id": posted_id,
        "receipt_hash": descriptor["receipt_hash"],
        "run_id": descriptor["run_id"],
        "descriptor_sha256": revision,
        "groups": 59,
        "selected_exact_amount": "58988.95",
        "selected_contributors": 6,
        "original_cell": cell
        if metadata is None
        else {"coordinate": "Base!S2", "value": "731.97"},
        "excluded_coordinate": "Base!S288",
    },
    "metadata": metadata,
    "requests": timings,
    "browser_acceptance": "PENDING",
    "release_accepted": False,
}
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(
    json.dumps(
        {
            "state": evidence["state"],
            "output": str(destination),
            "requests": len(timings),
        }
    )
)

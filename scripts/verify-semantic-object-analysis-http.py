"""Read-only HTTP proof for the published, measure-free SEG account table.

Requires an invocation produced after the matching API implementation was frozen.
This script never publishes, invokes Functions, edits objects or claims browser QA.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8062")
    parser.add_argument("--invocation", required=True, type=UUID)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output).resolve()
    assert destination.drive.upper() == "D:", "Evidence must stay on D:"
    token, _ = next(
        (key, grant)
        for key, grant in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if {"ingest", "ontology_read"} <= set(grant["permissions"])
        and "ontology_admin" not in grant["permissions"]
    )
    timings = []

    def call(path, body=None, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + token
        request = Request(
            args.api.rstrip("/") + "/v1/ontology/" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        started = perf_counter()
        try:
            with urlopen(request, timeout=60) as response:
                status, data = response.status, json.load(response)
        except HTTPError as exc:
            status, data = exc.code, json.load(exc)
        timings.append(
            {
                "path": path,
                "status": status,
                "seconds": round(perf_counter() - started, 3),
            }
        )
        return status, data

    def ok(path, body=None):
        status, data = call(path, body)
        assert status == 200, (path, status, data)
        return data

    def pin(row):
        return {key: row[key] for key in ("resource_id", "version_id", "content_hash")}

    company_id = "365aa5d9-c2ec-52e1-867a-50fe3415f486"
    company_pin = {
        "resource_id": company_id,
        "version_id": "928f83fe-09a5-5f73-82ad-83fcfa77af7b",
        "content_hash": "f1c3000ff2997d128f0d60f6f11197a9f2f720adf1949427e77993ed08516fcf",
    }
    chart_pin = {
        "resource_id": "8156f21a-d5c0-5a45-9ec1-2b4513e73071",
        "version_id": "ad4ba1e3-3258-58d9-b105-89e36391920c",
        "content_hash": "9f9bd24cbb57b500763d06bf6ae48c99e2e9e91dbe53266814f45cf9694e3463",
    }
    definition_pin = {
        "resource_id": "3a6c0fb2-47af-584f-acbf-415801c7ebd5",
        "version_id": "93eb5aae-9e04-5a5b-8595-c483d895737d",
        "content_hash": "9ee8927baae6f07b24806efca09e24263a25c40e187b8302cd14ee2b40895c27",
    }
    source_sha = "607e37da8aa8e05687c9898cc1577db070c082ece8281c7bd3a43e725aac73df"
    base = {"invocation_id": str(args.invocation), "company_id": company_id}
    original = ok("functions/invocations/" + str(args.invocation))
    assert original["status"] == "SUCCEEDED"
    result = ok("analysis/project", base)
    descriptor = result["descriptor"]
    assert (
        descriptor["contract"] == "semantic-analysis/2"
        and descriptor["row_noun"] == "objects"
    )
    assert descriptor["measure"] is None and descriptor["visual"] == "NONE"
    assert all(
        field["role"] != "MEASURE" and field["aggregation"] == "NONE"
        for field in descriptor["fields"]
    )
    assert descriptor["company"] == company_pin
    assert descriptor["receipt_hash"] == original["receipt_hash"]
    assert descriptor["function"] == original["output"]["function"]
    assert (
        descriptor["function"]["resource_id"] == "983c1f84-5cf0-557f-b5cd-8656a746f209"
    )
    assert descriptor["run_id"] == original["output"]["run_id"]
    assert (
        not descriptor["current_use_authorized"]
        and not descriptor["business_effect_authorized"]
    )
    assert (
        len(result["rows"])
        == result["total_rows"]
        == len(original["output"]["objects"])
        == 38
    )
    originals = {obj["resource_id"]: obj for obj in original["output"]["objects"]}
    for row in result["rows"]:
        ref = row["values"]["__resource"]["reference"]
        exact = originals[ref["resource_id"]]
        assert ref == row["trace"] == pin(exact)
        assert exact["object_type"] == "LocalAccount"
        assert (
            row["values"]["account_code"]["value"]
            == exact["attributes"]["account_code"]
        )
        assert row["values"]["chart_id"]["reference"] == chart_pin
    selected = next(
        row
        for row in result["rows"]
        if row["values"]["account_code"]["value"] == "1210"
    )
    assert selected["trace"] == {
        "resource_id": "509b173e-0883-52e9-8603-02fccda048c8",
        "version_id": "02b10e2c-5ad8-56bb-82dd-c0f1f7777113",
        "content_hash": "91b48a8d4db20b66214e3e882db767345aae08d19ea4327af9b57c34fd2d058d",
    }
    revision = result["descriptor_sha256"]
    selection = {
        **base,
        "descriptor_sha256": revision,
        "selected_row": selected["key"],
        "filters": [{"field": "account_code", "value": "1210"}],
        "group_by": "chart_id",
    }
    detail = ok("analysis/project", selection)
    assert detail["descriptor_sha256"] == revision and detail["rows"] == [selected]
    assert len(detail["sections"]) == 1 and detail["sections"][0]["row_keys"] == [
        selected["key"]
    ]
    contributor = detail["selection"]["contributor"]
    assert contributor.get("basis", "ORIGINAL_SOURCE") == "ORIGINAL_SOURCE"
    assert contributor["reference"] == definition_pin
    assert (
        contributor["source_sha256"] == source_sha
        and contributor["coordinate"] == "Sheet1!B189"
    )
    assert (
        contributor["document_id"]
        == "ir_ea498afd44a9e438752f41d7ed3ec8867fcaaa1466f1de865ea9a3bc4529eb40"
    )
    cell = next(c for c in contributor["cells"] if c["coordinate"] == "Sheet1!B189")
    assert cell["value"] == "1210" and cell["formula"] is None
    resumed = ok("analysis/project", json.loads(json.dumps(detail["request"])))
    assert resumed["descriptor_sha256"] == revision
    assert (
        resumed["rows"] == detail["rows"]
        and resumed["selection"] == detail["selection"]
    )
    known_at = descriptor["known_at"]
    params = urlencode(
        {"version_id": selected["trace"]["version_id"], "known_at": known_at}
    )
    inspected = ok(
        "operator/resources/" + selected["trace"]["resource_id"] + "?" + params
    )
    assert (
        pin(inspected["resource"]) == selected["trace"]
        and inspected["selection_mode"] == "EXACT_VERSION"
    )
    assert not inspected["current_use_authorized"]
    graph = ok("operator/trace/" + selected["trace"]["resource_id"] + "?" + params)
    assert graph["root_version_id"] == selected["trace"]["version_id"]
    edges = {
        (e["source_version_id"], e["target_version_id"], e["relation"])
        for e in graph["edges"]
    }
    assert (
        selected["trace"]["version_id"],
        chart_pin["version_id"],
        "FIELD:chart_id",
    ) in edges
    assert (
        chart_pin["version_id"],
        company_pin["version_id"],
        "FIELD:legal_entity_id",
    ) in edges
    assert (
        selected["trace"]["version_id"],
        definition_pin["version_id"],
        "BOUND_SOURCE:" + definition_pin["resource_id"],
    ) in edges
    definition_detail = ok(
        "operator/resources/"
        + definition_pin["resource_id"]
        + "?"
        + urlencode({"version_id": definition_pin["version_id"], "known_at": known_at})
    )
    assert pin(definition_detail["resource"]) == definition_pin
    assert (
        definition_detail["resource"]["attributes"]["evidence_id"]
        == "0074068a-99ea-5a03-8e61-15f7430b04d4"
    )
    refusal_codes = {
        "wrong_company": call(
            "analysis/project",
            {**base, "company_id": "c6f87828-9609-5b35-afa6-e894a0acfe41"},
        )[0],
        "stale_descriptor": call(
            "analysis/project", {**selection, "descriptor_sha256": "0" * 64}
        )[0],
        "forbidden_aggregate": call("analysis/project", {**base, "aggregation": "sum"})[
            0
        ],
        "anonymous": call("analysis/project", base, authenticated=False)[0],
    }
    assert refusal_codes == {
        "wrong_company": 404,
        "stale_descriptor": 409,
        "forbidden_aggregate": 422,
        "anonymous": 401,
    }
    evidence = {
        "state": "LOCAL_INTEGRATED_HTTP_PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "api": args.api,
        "writes_performed": False,
        "invocation_id": str(args.invocation),
        "receipt_hash": descriptor["receipt_hash"],
        "run_id": descriptor["run_id"],
        "function": descriptor["function"],
        "company": company_pin,
        "descriptor_sha256": revision,
        "object_count": 38,
        "all_object_pins_match_retained_output": True,
        "measure": None,
        "visual": "NONE",
        "filter_resume_verified": True,
        "selected_account": selected["trace"],
        "selected_definition": definition_pin,
        "original_chart_sha256": source_sha,
        "original_cell": cell,
        "trace_edges_verified": [
            "FIELD:chart_id",
            "FIELD:legal_entity_id",
            "BOUND_SOURCE",
        ],
        "refusals": refusal_codes,
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


if __name__ == "__main__":
    main()

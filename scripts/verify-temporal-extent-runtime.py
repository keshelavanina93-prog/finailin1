"""Verify complete source-date extent from exact retained first-week observations."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from finai_api.domain.review import Principal
from finai_api.services import function_execution

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "extent_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
KEY = "sog-source-dates:temporal-extent:v1"
SCHEMA = "bad94aa4-a02c-56fb-bc85-63e51e5b2282"
EVIDENCE = "71f45f39-35fb-56c1-b4b7-61e7edc56368"
SOURCE_HASH = "45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d"
FAMILY = "1c_journal:" + SOURCE_HASH + ":TR"


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def prepare(author, reviewer):
    query = {
        "object_type": "SourceJournalMovement",
        "filters": [
            {"field": "evidence_id", "value": EVIDENCE},
            {"field": "source_family", "value": FAMILY},
            {"field": "posting_date", "operator": "gte", "value": "2025-11-01"},
            {"field": "posting_date", "operator": "lt", "value": "2025-11-08"},
        ],
    }
    selected = shared.publish(
        author,
        reviewer,
        "ObjectSetDefinition",
        KEY,
        "SOG retained source dates: first seven days of November 2025",
        {"definition": query},
    )
    manifest = function_execution.manifest()
    implementation = {
        key: manifest[key]
        for key in (
            "implementation_id",
            "determinism",
            "code_sha256",
            "dependency_sha256",
        )
    }
    functions = {}
    for node in ("source_dates", "date_extent"):
        definition = {**implementation, "derived_property_ids": []}
        if node == "date_extent":
            definition["temporal_extent"] = {
                "schema_id": SCHEMA,
                "field": "posting_date",
            }
        functions[node] = shared.publish(
            author,
            reviewer,
            "FunctionDefinition",
            KEY if node == "date_extent" else KEY + ":source",
            "SOG source observations: " + node,
            {"object_set_id": selected["resource_id"], "definition": definition},
        )
    transformation = shared.publish(
        author,
        reviewer,
        "TransformationDefinition",
        KEY,
        "Retain SOG source dates and explain their observed extent",
        {
            "resource_budget": {
                "max_returned_rows": 46,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 2000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source_dates",
                        "function_id": functions["source_dates"]["resource_id"],
                        "limit": 23,
                        "offset": 0,
                    },
                    {
                        "node_id": "date_extent",
                        "function_id": functions["date_extent"]["resource_id"],
                        "limit": 23,
                        "offset": 0,
                        "depends_on": ["source_dates"],
                        "input_binding": {"upstream_node_id": "source_dates"},
                    },
                ],
                "outputs": [{"output_id": node, "node_id": node} for node in functions],
            },
        },
    )
    return {
        "object_set": pin(selected),
        "functions": {key: pin(value) for key, value in functions.items()},
        "transformation": pin(transformation),
        "query": query,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--start", action="store_true")
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument(
        "--request-id",
        help="Adopt an existing browser build without changing its request time",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin47-temporal-extent-runtime.json"),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    required = (
        {"ontology_admin", "ontology_propose", "ontology_read"}
        if args.prepare
        else {"read", "ingest", "ontology_read"}
    )
    token, author = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if required.issubset(grant["permissions"])
    )
    if args.prepare:
        reviewer = next(
            Principal.model_validate(grant)
            for grant in grants.values()
            if grant["actor_id"] != author.actor_id
            and grant["scope"]["tenant_id"] == str(author.scope.tenant_id)
            and {"ontology_admin", "ontology_review"}.issubset(grant["permissions"])
        )
        prepared = prepare(author, reviewer)
        save(args.output, {"phase": "DEFINITIONS_PREPARED", "prepared": prepared})
        print(json.dumps(prepared))
        return
    previous = json.loads(args.output.read_text(encoding="utf-8"))
    prepared = previous["prepared"]
    request = previous.get("request")
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + token},
        timeout=90,
        trust_env=False,
        follow_redirects=False,
    ) as client:

        def get(route, **kwargs):
            response = client.get(route, **kwargs)
            response.raise_for_status()
            return response.json()

        if args.request_id:
            adopted = get("/transformations/runs/" + args.request_id)["request"][
                "compiled_plan"
            ]["request"]
            assert (
                adopted["request_id"] == args.request_id
                and adopted["transformation"] == prepared["transformation"]
            )
            if request:
                assert request == adopted
            request = adopted
        if request is None:
            assert args.start
            now = datetime.now(UTC).isoformat()
            request = {
                "request_id": str(uuid4()),
                "transformation": prepared["transformation"],
                "valid_at": now,
                "known_at": now,
            }
        previous["request"] = request
        save(args.output, previous)
        if args.start:
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
        result = shared.shared.read_complete(
            client, request["request_id"], args.timeout
        )
        assert len(result["publications"]) == 1
        invocations = {}
        for item in result["publications"][0]["outputs"]:
            ref = item["value"]
            receipt = get("/functions/invocations/" + ref["invocation_id"])
            assert (
                receipt["status"] == "SUCCEEDED"
                and receipt["receipt_hash"] == ref["receipt_hash"]
            )
            assert receipt["output"]["run_id"] == ref["run_id"]
            invocations[item["slot"]] = receipt
        upstream = invocations["source_dates"]
        output = invocations["date_extent"]["output"]
        assert output["objects"] == upstream["output"]["objects"]
        assert output["query"] == upstream["output"]["query"]
        assert output["input_result"] == {
            "invocation_id": upstream["invocation_id"],
            "receipt_hash": upstream["receipt_hash"],
            "run_id": upstream["output"]["run_id"],
        }
        objects = output["objects"]
        assert output["total"] == len(objects) == 23 and output["next_offset"] is None
        assert all(
            obj["attributes"]["evidence_id"] == EVIDENCE
            and obj["attributes"]["source_family"] == FAMILY
            for obj in objects
        )
        dates = [obj["attributes"]["posting_date"] for obj in objects]
        assert min(dates) == "2025-11-01" and max(dates) == "2025-11-07"
        assert dates.count("2025-11-01") == 2 and dates.count("2025-11-07") == 6
        extent = output["temporal_extent"]
        assert extent["contract"] == "temporal-observation-extent/1"
        assert extent["authority"] == "OBSERVATION_EXTENT_ONLY"
        assert extent["coverage"] == "COMPLETE_BOUNDED_OBJECT_SET"
        assert extent["schema"]["resource_id"] == SCHEMA
        assert extent["field"] == "posting_date" and extent["kind"] == "date"
        assert extent["state"] == "AVAILABLE"
        assert extent["object_count"] == extent["value_count"] == 23
        assert extent["missing_count"] == extent["null_count"] == 0
        for side, boundary in (("earliest", "2025-11-01"), ("latest", "2025-11-07")):
            assert extent[side]["normalized_value"] == boundary
            witnesses = [
                {
                    **pin(obj),
                    "content_hash": obj["content_hash"],
                    "original_value": boundary,
                }
                for obj in objects
                if obj["attributes"]["posting_date"] == boundary
            ]
            assert extent[side]["witnesses"] == sorted(
                witnesses, key=lambda item: (item["resource_id"], item["version_id"])
            )
        boundary_objects = [
            obj
            for obj in objects
            if obj["attributes"]["posting_date"] in ("2025-11-01", "2025-11-07")
        ]
        evidence = []
        for obj in boundary_objects:
            trace = get(
                "/operator/trace/" + obj["resource_id"],
                params={
                    "version_id": obj["version_id"],
                    "known_at": request["known_at"],
                },
            )
            edge = next(
                edge
                for edge in trace["edges"]
                if edge["source_version_id"] == obj["version_id"]
                and edge["relation"] == "FIELD:evidence_id"
            )
            target = get(
                "/operator/resources/" + EVIDENCE,
                params={
                    "version_id": edge["target_version_id"],
                    "known_at": request["known_at"],
                },
            )["resource"]
            assert target["attributes"]["sha256"] == SOURCE_HASH
            evidence.append(
                {
                    "object": pin(obj),
                    "source_row_key": obj["attributes"]["source_row_key"],
                    "content_hash": obj["content_hash"],
                    "evidence": pin(target),
                    "evidence_hash": target["content_hash"],
                }
            )
        assert (
            output["current_use_authorized"] is False
            and output["business_effect_authorized"] is False
        )
        if previous.get("result"):
            assert shared.shared.retained_part(result) == shared.shared.retained_part(
                previous["result"]
            )
            assert invocations == previous["invocations"]
    save(
        args.output,
        {
            **previous,
            "phase": "TEMPORAL_EXTENT_VERIFIED",
            "result": result,
            "invocations": invocations,
            "boundary_evidence": evidence,
            "checked_at": datetime.now(UTC).isoformat(),
            "financial_period_authority": False,
        },
    )
    print("Exact retained source-date extent and boundary evidence verified.")


if __name__ == "__main__":
    main()

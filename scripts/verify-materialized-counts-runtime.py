"""Verify grouped source observation counts over exact retained materialization."""

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
    "materialized_counts_shared",
    ROOT / "scripts/verify-transformation-input-runtime.py",
)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
KEY = "sog-source-dates:materialized-counts:v1"
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
            {"field": "posting_date", "operator": "lt", "value": "2025-12-01"},
        ],
    }
    selected = shared.publish(
        author,
        reviewer,
        "ObjectSetDefinition",
        KEY,
        "SOG retained source dates: November 2025 selected observations",
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
    for node in ("source_dates", "date_counts"):
        definition = {
            **implementation,
            "derived_property_ids": [],
            "materialization": {"max_objects": 300, "max_pages": 2},
        }
        if node == "date_counts":
            definition["group_count"] = {
                "schema_id": SCHEMA,
                "fields": ["posting_date"],
            }
        functions[node] = shared.publish(
            author,
            reviewer,
            "FunctionDefinition",
            KEY if node == "date_counts" else KEY + ":source",
            "Count SOG observations by posting date"
            if node == "date_counts"
            else "Read SOG observations for date counts",
            {"object_set_id": selected["resource_id"], "definition": definition},
        )
    transformation = shared.publish(
        author,
        reviewer,
        "TransformationDefinition",
        KEY,
        "Count SOG observations by posting date",
        {
            "resource_budget": {
                "max_returned_rows": 600,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 2000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source_dates",
                        "function_id": functions["source_dates"]["resource_id"],
                        "limit": 200,
                        "offset": 0,
                    },
                    {
                        "node_id": "date_counts",
                        "function_id": functions["date_counts"]["resource_id"],
                        "limit": 200,
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
        default=Path(
            "docs/development/evidence/nin47-materialized-counts-runtime.json"
        ),
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
        output = invocations["date_counts"]["output"]
        assert output["objects"] == upstream["output"]["objects"]
        assert output["query"] == upstream["output"]["query"]
        assert output["input_result"] == {
            "invocation_id": upstream["invocation_id"],
            "receipt_hash": upstream["receipt_hash"],
            "run_id": upstream["output"]["run_id"],
        }
        objects = output["objects"]
        assert output["total"] == len(objects) == 246 and output["next_offset"] is None
        assert all(
            obj["attributes"]["evidence_id"] == EVIDENCE
            and obj["attributes"]["source_family"] == FAMILY
            for obj in objects
        )
        material = output["materialization"]
        assert material == upstream["output"]["materialization"]
        assert material["contract"] == "bounded-object-set-materialization/1"
        assert (
            material["coverage"]
            == output["coverage"]
            == "COMPLETE_BOUNDED_MATERIALIZATION"
        )
        assert material["hash_algorithm"] == "POSTGRES_JSONB_TEXT_UTF8_SHA256"
        assert material["object_count"] == 246 and material["page_count"] == 2
        assert material["max_objects"] == 300 and material["max_pages"] == 2
        assert pin(material["object_set"]) == prepared["object_set"]
        pages = material["pages"]
        assert [len(page["object_pins"]) for page in pages] == [200, 46]
        assert [page["query"]["offset"] for page in pages] == [0, 200]
        assert [page["next_offset"] for page in pages] == [200, None]
        assert all(
            page["total"] == 246 and page["query"]["limit"] == 200 for page in pages
        )
        assert all(len(page["page_hash"]) == 64 for page in pages)
        assert [item for page in pages for item in page["object_pins"]] == [
            {**pin(obj), "content_hash": obj["content_hash"]} for obj in objects
        ]
        assert len({(obj["resource_id"], obj["version_id"]) for obj in objects}) == 246
        for page in pages:
            for field in ("valid_at", "known_at", "filters"):
                assert page["query"][field] == output["query"][field]
        assert output["derived_values"] == [] and "temporal_extent" not in output
        dates = [obj["attributes"]["posting_date"] for obj in objects]
        assert min(dates) == "2025-11-01" and max(dates) == "2025-11-30"
        assert dates.count("2025-11-01") == 2 and dates.count("2025-11-30") == 140
        counts = output["group_counts"]
        assert counts["contract"] == "grouped-observation-counts/1"
        assert counts["authority"] == "OBSERVATION_COUNTS_ONLY"
        assert counts["coverage"] == "COMPLETE_BOUNDED_MATERIALIZATION"
        assert counts["schema"]["resource_id"] == SCHEMA
        assert counts["fields"] == ["posting_date"] and counts["object_count"] == 246
        expected = {}
        for obj in objects:
            expected.setdefault(obj["attributes"]["posting_date"], []).append(
                {**pin(obj), "content_hash": obj["content_hash"]}
            )
        actual = {}
        for group in counts["groups"]:
            assert len(group["key"]) == 1
            key = group["key"][0]
            assert key["field"] == "posting_date" and key["state"] == "VALUE"
            date = key["value"]
            assert date not in actual
            assert group["count"] == len(group["contributors"])
            actual[date] = group["contributors"]
        order = lambda value: (value["resource_id"], value["version_id"])
        assert {date: sorted(values, key=order) for date, values in actual.items()} == {
            date: sorted(values, key=order) for date, values in expected.items()
        }
        assert sum(group["count"] for group in counts["groups"]) == 246
        boundary_objects = [
            next(obj for obj in objects if obj["attributes"]["posting_date"] == date)
            for date in ("2025-11-01", "2025-11-30")
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
            "phase": "MATERIALIZED_COUNTS_VERIFIED",
            "result": result,
            "invocations": invocations,
            "representative_boundary_evidence": evidence,
            "checked_at": datetime.now(UTC).isoformat(),
            "financial_period_authority": False,
        },
    )
    print(
        "Exact materialized counts, contributor conservation and representative evidence verified."
    )


if __name__ == "__main__":
    main()

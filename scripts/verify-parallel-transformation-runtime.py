"""Verify bounded parallel source reads and a two-parent retained-input dependency."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from finai_api.domain.review import Principal
from finai_api.services import function_execution, resources

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "parallel_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
KEY = "sog-source-contexts:parallel-function-build:v2"
SOURCES = {
    "budget_context": "2cc5e885-54f5-5b58-9359-29fd06bf8eac",
    "source_record": "434c6e5a-85dc-5d06-b724-31020771254e",
}


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def prepare(author, reviewer):
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
    sources, sets, functions = {}, {}, {}
    for node, identity in SOURCES.items():
        sources[node] = resources.get_resource(author, UUID(identity))["resource"]
        assert (
            sources[node]["attributes"]["evidence_id"]
            == "71f45f39-35fb-56c1-b4b7-61e7edc56368"
        )
        sets[node] = shared.publish(
            author,
            reviewer,
            "ObjectSetDefinition",
            KEY + ":" + node,
            "Original SOG source context: " + node,
            {
                "definition": {
                    "object_type": sources[node]["object_type"],
                    "resource_ids": [identity],
                }
            },
        )
        functions[node] = shared.publish(
            author,
            reviewer,
            "FunctionDefinition",
            KEY + ":" + node,
            "Read original SOG source context: " + node,
            {
                "object_set_id": sets[node]["resource_id"],
                "definition": {**implementation, "derived_property_ids": []},
            },
        )
    functions["joined"] = shared.publish(
        author,
        reviewer,
        "FunctionDefinition",
        KEY + ":joined",
        "Inspect retained budget context after both source reads",
        {
            "object_set_id": sets["budget_context"]["resource_id"],
            "definition": {**implementation, "derived_property_ids": []},
        },
    )
    nodes = [
        {
            "node_id": node,
            "function_id": functions[node]["resource_id"],
            "limit": 1,
            "offset": 0,
        }
        for node in ("budget_context", "source_record")
    ]
    nodes.append(
        {
            "node_id": "joined",
            "function_id": functions["joined"]["resource_id"],
            "limit": 1,
            "offset": 0,
            "depends_on": ["budget_context", "source_record"],
            "input_binding": {"upstream_node_id": "budget_context"},
        }
    )
    transformation = shared.publish(
        author,
        reviewer,
        "TransformationDefinition",
        KEY,
        "Parallel budget classification and original source record reads",
        {
            "execution_policy": {"max_concurrent_nodes": 2},
            "resource_budget": {
                "max_returned_rows": 3,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 1000000,
            },
            "definition": {
                "nodes": nodes,
                "outputs": [{"output_id": node, "node_id": node} for node in functions],
            },
        },
    )
    return {
        "sources": sources,
        "functions": {key: pin(value) for key, value in functions.items()},
        "transformation": pin(transformation),
    }


def intervals(events):
    """Return only persisted execution intervals; absence never proves overlap."""
    spans = {}
    for node in ("budget_context", "source_record", "joined"):
        starts = [
            e for e in events if e.get("node") == node and e.get("state") == "RUNNING"
        ]
        ends = [
            e for e in events if e.get("node") == node and e.get("state") == "COMPLETED"
        ]
        if len(starts) == len(ends) == 1:
            spans[node] = {
                "started_at": starts[0]["created_at"],
                "completed_at": ends[0]["created_at"],
                "start_event_id": starts[0]["event_id"],
                "terminal_event_id": ends[0]["event_id"],
            }
    overlap = False
    if all(node in spans for node in ("budget_context", "source_record")):
        first, second = spans["budget_context"], spans["source_record"]
        overlap = max(
            datetime.fromisoformat(first["started_at"]),
            datetime.fromisoformat(second["started_at"]),
        ) < min(
            datetime.fromisoformat(first["completed_at"]),
            datetime.fromisoformat(second["completed_at"]),
        )
    if "joined" in spans and all(
        node in spans for node in ("budget_context", "source_record")
    ):
        assert datetime.fromisoformat(spans["joined"]["started_at"]) >= max(
            datetime.fromisoformat(spans[node]["completed_at"])
            for node in ("budget_context", "source_record")
        )
    return {
        "persisted_node_intervals": spans,
        "actual_overlap_demonstrated": overlap,
        "evidence_basis": "PERSISTED_START_TO_COMPLETION_INTERVALS"
        if spans
        else "EXECUTION_INTERVALS_UNAVAILABLE",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--start", action="store_true")
    modes.add_argument("--readback", action="store_true")
    parser.add_argument("--request-id", help="Adopt an existing browser-started build")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/development/evidence/nin12-parallel-transformation-runtime.json"
        ),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    required = (
        {"ontology_admin", "ontology_read", "ontology_propose"}
        if args.prepare
        else {"read", "ontology_read", "ingest"}
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
        print(json.dumps(prepared["transformation"]))
        return
    previous = json.loads(args.output.read_text(encoding="utf-8"))
    prepared = previous["prepared"]
    request = previous.get("request")
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + token},
        timeout=60,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        if args.request_id:
            response = client.get("/transformations/runs/" + args.request_id)
            response.raise_for_status()
            request = response.json()["request"]["compiled_plan"]["request"]
            assert (
                request["request_id"] == args.request_id
                and request["transformation"] == prepared["transformation"]
            )
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
        assert result["publications"][0]["authority"] == "EXECUTION_ONLY"
        invocations = {}
        for item in result["publications"][0]["outputs"]:
            reference = item["value"]
            response = client.get(
                "/functions/invocations/" + reference["invocation_id"]
            )
            response.raise_for_status()
            invocation = response.json()
            assert (
                invocation["status"] == "SUCCEEDED"
                and invocation["receipt_hash"] == reference["receipt_hash"]
            )
            assert invocation["output"]["run_id"] == reference["run_id"]
            invocations[item["slot"]] = invocation
        assert set(invocations) == {"budget_context", "source_record", "joined"}
        for node in SOURCES:
            obj = invocations[node]["output"]["objects"]
            assert len(obj) == 1 and pin(obj[0]) == pin(prepared["sources"][node])
            assert obj[0]["attributes"] == prepared["sources"][node]["attributes"]
        upstream, joined = (
            invocations["budget_context"],
            invocations["joined"]["output"],
        )
        assert joined["objects"] == upstream["output"]["objects"]
        assert joined["input_result"] == {
            "invocation_id": upstream["invocation_id"],
            "receipt_hash": upstream["receipt_hash"],
            "run_id": upstream["output"]["run_id"],
        }
        assert joined["query"] == upstream["output"]["query"]
        timing = intervals(result["events"])
        if previous.get("result"):
            assert shared.shared.retained_part(
                previous["result"]
            ) == shared.shared.retained_part(result)
            assert previous["invocations"] == invocations
    save(
        args.output,
        {
            **previous,
            "phase": "PARALLEL_OVERLAP_VERIFIED"
            if timing["actual_overlap_demonstrated"]
            else "BUILD_VERIFIED_OVERLAP_UNPROVEN",
            "checked_at": datetime.now(UTC).isoformat(),
            "result": result,
            "invocations": invocations,
            "timing": timing,
            "financial_authority_established": False,
        },
    )
    print(
        "Build and retained inputs verified; actual overlap: "
        + str(timing["actual_overlap_demonstrated"])
    )


if __name__ == "__main__":
    main()

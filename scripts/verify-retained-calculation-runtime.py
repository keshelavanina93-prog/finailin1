"""Verify real source-label calculation consumed by a durable downstream Function."""

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
loader = importlib.util.spec_from_file_location(
    "retained_calculation_shared",
    ROOT / "scripts/verify-transformation-input-runtime.py",
)
shared = importlib.util.module_from_spec(loader)
loader.loader.exec_module(shared)
runtime = shared.shared
KEY = "source-account:retained-calculation-chain:v1"
ACCOUNT = "00c93da8-3ab9-5597-aaf6-ea79b7307d32"
SCHEMA = "e365d1cd-40f1-5fa5-8343-3db93f32e4aa"


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def publish_label(author, reviewer, corrected=False):
    args = [
        {"op": "field", "field": "account_code"},
        {"op": "literal", "value": " | "},
        {"op": "field", "field": "source_name"},
    ]
    if corrected:
        args.append({"op": "literal", "value": ":"})
    return shared.publish(
        author,
        reviewer,
        "DerivedProperty",
        KEY + ":label",
        "Observed source account label"
        + (" with reviewed colon suffix" if corrected else ""),
        {
            "schema_id": SCHEMA,
            "definition": {
                "name": "retained_source_label",
                "result_kind": "text",
                "expression": {"op": "concat", "args": args},
            },
        },
    )


def prepare(author, reviewer):
    label = publish_label(author, reviewer)
    downstream = shared.publish(
        author,
        reviewer,
        "DerivedProperty",
        KEY + ":consumer",
        "Text composed from the retained source-label result",
        {
            "schema_id": SCHEMA,
            "definition": {
                "name": "consumed_source_label",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [
                        {"op": "derived", "property": pin(label)},
                        {"op": "literal", "value": " | retained"},
                    ],
                },
            },
        },
    )
    selected = shared.publish(
        author,
        reviewer,
        "ObjectSetDefinition",
        KEY,
        "Original retained source account for calculated input",
        {
            "definition": {
                "object_type": "SourceAccountDefinition",
                "resource_ids": [ACCOUNT],
            }
        },
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
    for node, property_resource in (
        ("source_label", label),
        ("consumed_label", downstream),
    ):
        definition = {
            **implementation,
            "derived_property_ids": [property_resource["resource_id"]],
        }
        if node == "consumed_label":
            definition["retained_properties"] = [pin(label)]
        functions[node] = shared.publish(
            author,
            reviewer,
            "FunctionDefinition",
            KEY + ":" + node,
            "Source observation calculation: " + node,
            {"object_set_id": selected["resource_id"], "definition": definition},
        )
    transformation = shared.publish(
        author,
        reviewer,
        "TransformationDefinition",
        KEY,
        "Calculate and consume one retained source-account label",
        {
            "resource_budget": {
                "max_returned_rows": 2,
                "max_derived_evaluations": 2,
                "max_published_result_bytes": 1000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source_label",
                        "function_id": functions["source_label"]["resource_id"],
                        "offset": 0,
                        "limit": 1,
                    },
                    {
                        "node_id": "consumed_label",
                        "function_id": functions["consumed_label"]["resource_id"],
                        "offset": 0,
                        "limit": 1,
                        "depends_on": ["source_label"],
                        "input_binding": {"upstream_node_id": "source_label"},
                    },
                ],
                "outputs": [{"output_id": node, "node_id": node} for node in functions],
            },
        },
    )
    return {
        "label": pin(label),
        "consumer": pin(downstream),
        "object_set": pin(selected),
        "functions": {key: pin(value) for key, value in functions.items()},
        "transformation": pin(transformation),
    }


def verify(client, result, prepared):
    assert (
        result["current_use_authorized"] is False
        and result["business_effect_authorized"] is False
    )
    assert len(result["publications"]) == 1
    publication = result["publications"][0]
    assert publication["authority"] == "EXECUTION_ONLY"
    invocations = {}
    for item in publication["outputs"]:
        ref = item["value"]
        response = client.get("/functions/invocations/" + ref["invocation_id"])
        response.raise_for_status()
        receipt = response.json()
        assert receipt["status"] == "SUCCEEDED"
        assert receipt["receipt_hash"] == ref["receipt_hash"]
        assert receipt["output"]["run_id"] == ref["run_id"]
        invocations[item["slot"]] = receipt
    upstream, downstream = invocations["source_label"], invocations["consumed_label"]
    first, second = upstream["output"], downstream["output"]
    assert first["objects"] == second["objects"] and len(first["objects"]) == 1
    obj = first["objects"][0]
    assert obj["resource_id"] == ACCOUNT and obj["evidence_class"] == "SOURCE_BOUND"
    expected = (
        obj["attributes"]["account_code"] + " | " + obj["attributes"]["source_name"]
    )
    assert first["derived_values"][0]["value"] == expected
    assert second["derived_values"][0]["value"] == expected + " | retained"
    assert first["query"] == second["query"]
    source_result = {
        "invocation_id": upstream["invocation_id"],
        "receipt_hash": upstream["receipt_hash"],
        "run_id": first["run_id"],
    }
    assert second["input_result"] == source_result
    assert second["coverage"] == "RETAINED_INPUT_PAGE_ONLY"
    dependency = second["derived_values"][0]["dependency_values"][0]
    assert dependency["definition_id"] == prepared["label"]["resource_id"]
    assert dependency["definition_version_id"] == prepared["label"]["version_id"]
    assert (
        dependency["value"] == expected and dependency["source_result"] == source_result
    )
    assert dependency["source_fields"] == []
    assert len(second["consumed_property_values"]) == 1
    consumed = second["consumed_property_values"][0]
    assert consumed["value"] == expected and consumed["source_result"] == source_result
    for output in (first, second):
        assert (
            output["current_use_authorized"] is False
            and output["business_effect_authorized"] is False
        )
    return {
        "invocations": invocations,
        "source_result": source_result,
        "exact_original_objects_equal": True,
        "calculated_value_receipt_binding_verified": True,
        "no_rerun_requires_focused_backend_evaluator_evidence": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    for name in ("prepare", "correct", "replay", "read-only"):
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/development/evidence/nin47-retained-calculation-runtime.json"
        ),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    required = (
        {"ontology_admin", "ontology_propose", "ontology_read"}
        if args.prepare or args.correct
        else {"read", "ontology_read", "ingest"}
    )
    token, author = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if required.issubset(grant["permissions"])
    )
    if args.prepare or args.correct:
        reviewer = next(
            Principal.model_validate(grant)
            for grant in grants.values()
            if grant["actor_id"] != author.actor_id
            and grant["scope"]["tenant_id"] == str(author.scope.tenant_id)
            and {"ontology_admin", "ontology_review"}.issubset(grant["permissions"])
        )
    if args.prepare:
        prepared = prepare(author, reviewer)
        save(args.output, {"phase": "DEFINITIONS_PREPARED", "prepared": prepared})
        print(json.dumps(prepared))
        return
    previous = json.loads(args.output.read_text(encoding="utf-8"))
    prepared = previous["prepared"]
    if args.correct:
        assert previous.get("result") and not previous.get("correction")
        previous["correction"] = pin(publish_label(author, reviewer, corrected=True))
        save(args.output, previous)
    request = previous.get("request")
    if request is None:
        assert not (args.replay or args.read_only)
        now = datetime.now(UTC).isoformat()
        request = {
            "request_id": str(uuid4()),
            "transformation": prepared["transformation"],
            "valid_at": now,
            "known_at": now,
        }
        previous["request"] = request
        save(args.output, previous)
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + token},
        timeout=60,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        if not (args.read_only or args.correct):
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
            assert (
                response.json()["workflow_id"]
                == "transformation:" + request["request_id"]
            )
        result = runtime.read_complete(client, request["request_id"], args.timeout)
        proof = verify(client, result, prepared)
        if previous.get("result"):
            assert runtime.retained_part(result) == runtime.retained_part(
                previous["result"]
            )
            assert proof == previous["chain"]
        if args.correct:
            reference = previous["correction"]
            response = client.post(
                "/model/derived/query",
                json={
                    "query": {
                        "object_type": "SourceAccountDefinition",
                        "resource_ids": [ACCOUNT],
                        "valid_at": request["valid_at"],
                        "known_at": request["known_at"],
                        "limit": 1,
                    },
                    "definitions": [reference["resource_id"]],
                    "definition_versions": {
                        reference["resource_id"]: reference["version_id"]
                    },
                },
            )
            response.raise_for_status()
            corrected = response.json()
            original = proof["invocations"]["source_label"]["output"]
            assert corrected["objects"] == original["objects"]
            assert corrected["derived_values"][0]["status"] == "AVAILABLE"
            assert (
                corrected["derived_values"][0]["value"]
                == original["derived_values"][0]["value"] + ":"
            )
            assert (
                corrected["derived_values"][0]["definition_version_id"]
                == reference["version_id"]
            )
            assert reference["version_id"] != prepared["label"]["version_id"]
            reopened = client.get("/model/fact-runs/" + corrected["run_id"])
            reopened.raise_for_status()
            assert reopened.json() == corrected
            previous["corrected_calculation"] = corrected
    save(
        args.output,
        {
            **previous,
            "phase": "CORRECTION_REPLAY_VERIFIED"
            if previous.get("corrected_calculation")
            else "RUNTIME_VERIFIED",
            "replayed_existing_receipts": bool(previous.get("result")),
            "checked_at": datetime.now(UTC).isoformat(),
            "result": result,
            "chain": proof,
            "financial_authority_established": False,
            "mid_step_crash_recovery_demonstrated": False,
            "read_only_verification": args.read_only,
        },
    )
    print(
        "Real source calculated-output consumption and exact retained history verified."
    )


if __name__ == "__main__":
    main()

"""Verify durable build-to-canonical-review continuity using retained Department metadata."""

import argparse
import importlib.util
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import function_execution, resources

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "binding_build_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
KEY = "sog-department:build-binding-review:v1"
SOURCE = "2bd64825-e320-5039-b163-2064a1a71c82"
TARGET = "1751ddc9-6ff0-57c9-8d22-cfaade27b62c"


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def prepare(author, reviewer):
    source = resources.get_resource(author, UUID(SOURCE))["resource"]
    target = resources.get_resource(author, UUID(TARGET))["resource"]
    assert source["attributes"]["source_header"] == "Department"
    assert source["attributes"]["source_column"] == "AA"
    assert source["attributes"]["dimension_id"] == TARGET
    assert target["display_name"] == "Department", (
        "Choose only the unmodified authentic target"
    )
    schema = str(
        canonical_id(author.scope.tenant_id, "SchemaDefinition", "CompanyDimension")
    )
    derived = shared.publish(
        author,
        reviewer,
        "DerivedProperty",
        KEY + ":display",
        "Department display from original header and column",
        {
            "schema_id": schema,
            "definition": {
                "name": "source_department_display",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [
                        {"op": "field", "field": "source_header"},
                        {"op": "literal", "value": " \u00b7 source column "},
                        {"op": "field", "field": "source_column"},
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
        "Original Department source context",
        {"definition": {"object_type": "CompanyDimension", "resource_ids": [SOURCE]}},
    )
    manifest = function_execution.manifest()
    function = shared.publish(
        author,
        reviewer,
        "FunctionDefinition",
        KEY,
        "Calculate Department display for independent review",
        {
            "object_set_id": selected["resource_id"],
            "definition": {
                **{
                    key: manifest[key]
                    for key in (
                        "implementation_id",
                        "determinism",
                        "code_sha256",
                        "dependency_sha256",
                    )
                },
                "derived_property_ids": [derived["resource_id"]],
            },
        },
    )
    binding = shared.publish(
        author,
        reviewer,
        "ObjectBinding",
        KEY,
        "Propose calculated display for the existing Department dimension",
        {
            "source_schema_id": schema,
            "target_schema_id": str(
                canonical_id(
                    author.scope.tenant_id, "SchemaDefinition", "DimensionDefinition"
                )
            ),
            "definition": {
                "identity_mode": "CANONICAL_REFERENCE",
                "identity_field": "dimension_id",
                "display_property": pin(derived),
                "fields": [],
            },
        },
    )
    transformation = shared.publish(
        author,
        reviewer,
        "TransformationDefinition",
        KEY,
        "Calculate Department display and wait for canonical review",
        {
            "resource_budget": {
                "max_returned_rows": 1,
                "max_derived_evaluations": 1,
                "max_published_result_bytes": 1000000,
            },
            "binding_review": {
                "binding_id": binding["resource_id"],
                "source_node_id": "department_display",
                "rationale": "Review only the calculated Department display from its retained source header and column; preserve all target attributes and source observations.",
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "department_display",
                        "function_id": function["resource_id"],
                        "limit": 1,
                        "offset": 0,
                    }
                ],
                "outputs": [
                    {"output_id": "department_display", "node_id": "department_display"}
                ],
            },
        },
    )
    return {
        "source": source,
        "target": target,
        "property": pin(derived),
        "binding": pin(binding),
        "function": pin(function),
        "transformation": pin(transformation),
        "expected_display": source["attributes"]["source_header"]
        + " \u00b7 source column "
        + source["attributes"]["source_column"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    for name in ("prepare", "start", "inspect", "approve", "readback"):
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument(
        "--request-id", help="Adopt the real build request started from the browser"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/development/evidence/nin12-transformation-binding-runtime.json"
        ),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    permissions = (
        {"ontology_admin", "ontology_propose", "ontology_read"}
        if args.prepare or args.approve
        else {"read", "ontology_read", "ingest"}
    )
    token, author = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if permissions.issubset(grant["permissions"])
    )
    if args.prepare or args.approve:
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

        def get(route):
            response = client.get(route)
            response.raise_for_status()
            return response.json()

        if args.request_id:
            result = get("/transformations/runs/" + args.request_id)
            # Use the run's own frozen invocation; never replace its times with now.
            request = result["request"]["compiled_plan"]["request"]
            assert request["request_id"] == args.request_id
            assert request["transformation"] == prepared["transformation"]
        if request is None:
            assert args.start, "Start or adopt a browser request first"
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
        deadline = time.monotonic() + args.timeout
        while True:
            result = get("/transformations/runs/" + request["request_id"])
            gate = result.get("binding_review")
            if (
                gate
                and gate.get("operation_id")
                and (
                    result.get("execution", {}).get("state")
                    == "AWAITING_BINDING_REVIEW"
                    or gate["state"] in {"APPROVED", "REJECTED", "CANCELLED"}
                )
            ):
                break
            assert time.monotonic() < deadline, (
                "Build did not reach its binding review gate"
            )
            time.sleep(1)
        operation = get("/operations/" + gate["operation_id"])
        reference = gate["input_result"]
        invocation = get("/functions/invocations/" + reference["invocation_id"])
        assert invocation["status"] == "SUCCEEDED"
        assert invocation["receipt_hash"] == reference["receipt_hash"]
        assert invocation["output"]["run_id"] == reference["run_id"]
        assert (
            invocation["output"]["derived_values"][0]["value"]
            == prepared["expected_display"]
        )
        assert pin(invocation["output"]["objects"][0]) == pin(prepared["source"])
        if previous.get("invocation"):
            assert invocation == previous["invocation"]
        previous["invocation"] = invocation
        proposal = operation["proposal"]["proposal"]
        mutation = proposal["mutations"][0]
        assert len(proposal["mutations"]) == 1 and mutation["resource_id"] == TARGET
        assert mutation["display_name"] == prepared["expected_display"]
        assert mutation["attributes"] == prepared["target"]["attributes"]
        assert get("/resources/" + SOURCE)["resource"] == prepared["source"]
        if operation["state"] != "PUBLISHED":
            assert not result["publications"]
            assert get("/resources/" + TARGET)["resource"] == prepared["target"]
            assert result["execution"]["state"] == "AWAITING_BINDING_REVIEW"
            snapshot = {
                "operation": operation,
                "binding_review": gate,
                "proposal": proposal,
            }
            if previous.get("pending"):
                assert snapshot == previous["pending"]
            previous["pending"] = snapshot
            previous["phase"] = "AWAITING_BINDING_REVIEW_VERIFIED"
        if args.approve:
            assert previous.get("pending") and operation["state"] == "PENDING_REVIEW"
            resources.review(
                reviewer,
                UUID(operation["prepared_proposal_id"]),
                ResourceReview(
                    decision="APPROVED",
                    rationale="Independent review of the exact calculated Department display; canonical identity, target attributes and original source preserved.",
                ),
            )
        if args.approve or args.readback:
            result = shared.shared.read_complete(
                client, request["request_id"], args.timeout
            )
            assert len(result["publications"]) == 1
            target = get("/resources/" + TARGET)["resource"]
            assert target["display_name"] == prepared["expected_display"]
            assert target["attributes"] == prepared["target"]["attributes"]
            assert target["version_id"] != prepared["target"]["version_id"]
            if previous.get("completed"):
                assert shared.shared.retained_part(
                    result
                ) == shared.shared.retained_part(previous["completed"])
            previous.update(
                completed=result,
                published_target=target,
                phase="REVIEWED_BUILD_PUBLICATION_VERIFIED",
            )
    save(
        args.output,
        {
            **previous,
            "checked_at": datetime.now(UTC).isoformat(),
            "financial_authority_established": False,
        },
    )
    print(previous["phase"])


if __name__ == "__main__":
    main()

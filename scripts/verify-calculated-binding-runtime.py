"""Review a calculated display-name update to an existing source-backed dimension."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import function_execution, resources

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "calculated_binding_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(loader)
loader.loader.exec_module(shared)
KEY = "sog-region:calculated-display-binding:v1"
SOURCE = "7959af7f-a1bb-5573-8006-d1fc14f58681"
TARGET = "e241052e-4f47-56b6-b1ea-fab72d17f0a7"
DISPLAY = "Region \u00b7 source column Y"


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def prepare(author, reviewer):
    source = resources.get_resource(author, UUID(SOURCE))["resource"]
    target = resources.get_resource(author, UUID(TARGET))["resource"]
    assert source["attributes"]["source_column"] == "Y"
    assert source["attributes"]["source_header"] == "Region"
    assert source["attributes"]["dimension_id"] == TARGET
    source_schema = str(
        canonical_id(author.scope.tenant_id, "SchemaDefinition", "CompanyDimension")
    )
    target_schema = str(
        canonical_id(author.scope.tenant_id, "SchemaDefinition", "DimensionDefinition")
    )
    property_resource = shared.publish(
        author,
        reviewer,
        "DerivedProperty",
        KEY + ":display",
        "Region display from original source column",
        {
            "schema_id": source_schema,
            "definition": {
                "name": "observed_region_display",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [
                        {"op": "literal", "value": "Region \u00b7 source column "},
                        {"op": "field", "field": "source_column"},
                    ],
                },
            },
        },
    )
    query = {"object_type": "CompanyDimension", "resource_ids": [SOURCE]}
    selected = shared.publish(
        author,
        reviewer,
        "ObjectSetDefinition",
        KEY,
        "Original SOG Region source context",
        {"definition": query},
    )
    manifest = function_execution.manifest()
    function = shared.publish(
        author,
        reviewer,
        "FunctionDefinition",
        KEY,
        "Calculate display from retained Region source context",
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
                "derived_property_ids": [property_resource["resource_id"]],
            },
        },
    )
    binding = shared.publish(
        author,
        reviewer,
        "ObjectBinding",
        KEY,
        "Review calculated Region display on the existing dimension",
        {
            "source_schema_id": source_schema,
            "target_schema_id": target_schema,
            "definition": {
                "identity_mode": "CANONICAL_REFERENCE",
                "identity_field": "dimension_id",
                "display_property": pin(property_resource),
                "fields": [],
            },
        },
    )
    return {
        "source": source,
        "target": target,
        "property": pin(property_resource),
        "function": pin(function),
        "binding": pin(binding),
        "query": query,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    for name in ("prepare", "calculate", "proposal", "approve", "replay"):
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument(
        "--operation-id", help="Inspect an operation already created in the browser"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin6-calculated-binding-runtime.json"),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token, author = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if {"ontology_admin", "ontology_propose", "ontology_read"}.issubset(
            grant["permissions"]
        )
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
        print(
            json.dumps(
                {key: prepared[key] for key in ("function", "binding", "property")}
            )
        )
        return
    previous = json.loads(args.output.read_text(encoding="utf-8"))
    prepared = previous["prepared"]
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

        if args.calculate:
            assert not previous.get("operation"), (
                "Retain the original calculation after proposal preparation"
            )
            request = previous.get("function_request")
            if request is None:
                now = datetime.now(UTC).isoformat()
                request = {
                    "request_id": str(uuid4()),
                    "function": prepared["function"],
                    "valid_at": now,
                    "known_at": now,
                    "offset": 0,
                    "limit": 1,
                }
                previous["function_request"] = request
                save(args.output, previous)
            response = client.post("/functions/invocations", json=request)
            response.raise_for_status()
            invocation = get("/functions/invocations/" + request["request_id"])
            assert invocation["status"] == "SUCCEEDED"
            assert invocation["output"]["derived_values"][0]["value"] == DISPLAY
            assert pin(invocation["output"]["objects"][0]) == pin(prepared["source"])
            previous["invocation"] = invocation
            previous.setdefault(
                "binding_request",
                {
                    "request_id": str(uuid4()),
                    "binding_id": prepared["binding"]["resource_id"],
                    "binding_version_id": prepared["binding"]["version_id"],
                    "query": invocation["output"]["query"],
                    "input_result": {"invocation_id": invocation["invocation_id"]},
                    "rationale": "Review only the calculated display name of the existing Region dimension; preserve its attributes and original source context. No financial authority.",
                },
            )
            previous["phase"] = "CALCULATION_RETAINED"
        if args.proposal:
            response = client.post(
                "/operations/bindings", json=previous["binding_request"]
            )
            response.raise_for_status()
            previous["operation"] = response.json()
        identity = args.operation_id or (previous.get("operation") or {}).get(
            "operation_id"
        )
        if identity:
            operation = get("/operations/" + identity)
            detail = operation["proposal"]
            assert detail is not None
            proposal = detail["proposal"]
            assert len(proposal["mutations"]) == 1
            mutation = proposal["mutations"][0]
            assert mutation["resource_id"] == TARGET
            assert mutation["display_name"] == DISPLAY
            assert mutation["attributes"] == prepared["target"]["attributes"]
            assert mutation["expected_version_id"] == prepared["target"]["version_id"]
            assert get("/resources/" + SOURCE)["resource"] == prepared["source"]
            if operation["state"] != "PUBLISHED":
                assert get("/resources/" + TARGET)["resource"] == prepared["target"]
                previous["pending_operation"] = operation
                previous["phase"] = "PENDING_PROPOSAL_VERIFIED"
            if args.approve:
                assert operation["state"] == "PENDING_REVIEW"
                resources.review(
                    reviewer,
                    UUID(operation["prepared_proposal_id"]),
                    ResourceReview(
                        decision="APPROVED",
                        rationale="Independently reviewed calculated Region display; exact existing identity and attributes preserved, with retained Function provenance.",
                    ),
                )
                operation = get("/operations/" + identity)
            if operation["state"] == "PUBLISHED":
                target = get("/resources/" + TARGET)["resource"]
                assert target["version_id"] != prepared["target"]["version_id"]
                assert (
                    target["display_name"] == DISPLAY
                    and target["attributes"] == prepared["target"]["attributes"]
                )
                trace = get(
                    "/operator/trace/" + TARGET,
                    params={"version_id": target["version_id"]},
                )
                node_pins = {
                    (node["resource_id"], node["version_id"]) for node in trace["nodes"]
                }
                for ref in (
                    prepared["source"],
                    prepared["function"],
                    prepared["property"],
                ):
                    assert (ref["resource_id"], ref["version_id"]) in node_pins
                if previous.get("published_target"):
                    assert target == previous["published_target"]
                previous.update(
                    published_target=target,
                    trace=trace,
                    phase="REVIEWED_PUBLICATION_VERIFIED",
                )
            previous["operation"] = operation
        elif not args.calculate:
            raise ValueError(
                "Select calculate, proposal, or an existing browser operation"
            )
        if previous.get("invocation"):
            assert (
                get("/functions/invocations/" + previous["invocation"]["invocation_id"])
                == previous["invocation"]
            )
        if args.replay:
            previous["readback_verified_at"] = datetime.now(UTC).isoformat()
            previous["retained_invocation_unchanged"] = True
            previous["published_version_unchanged"] = bool(previous.get("published_target"))
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

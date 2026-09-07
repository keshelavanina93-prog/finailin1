"""Prove exact retained source-object inputs across two shared Function steps."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import function_execution, resources
from finai_api.services.workspace import WorkspaceError

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "shared_build_proof", ROOT / "scripts/verify-transformation-runtime.py"
)
shared = importlib.util.module_from_spec(loader)
loader.loader.exec_module(shared)
KEY = "source-accounts:retained-input-chain:v1"
FUNCTION_KEY = "source-accounts:retained-object-labels:v1"
DERIVED_PROPERTY = "b9fbde64-2cc8-4c4e-bf44-fe8fbb38c13a"


def publish(author, reviewer, kind, key, title, attributes):
    identity = canonical_id(author.scope.tenant_id, kind, key)
    previous = None
    try:
        previous = resources.get_resource(author, identity)["resource"]
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
    proposal = ResourceProposal(
        title=title,
        rationale="Review exact retained source observation processing; no accounting or business-effect authority",
        access_entity=author.scope.legal_entity_id,
        mutations=[
            ResourceMutation(
                resource_id=identity,
                object_type=kind,
                identity_key=key,
                display_name=title,
                valid_from=datetime.now(UTC),
                attributes=attributes,
                expected_version_id=UUID(previous["version_id"]) if previous else None,
            )
        ],
    )
    resources.propose(author, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independent review of pinned Functions, retained result provenance and bounded observation processing",
        ),
    )
    return resources.get_resource(author, identity)["resource"]


def prepare(author, reviewer):
    source_id = canonical_id(
        author.scope.tenant_id, "FunctionDefinition", shared.FUNCTION_KEY
    )
    source = resources.get_resource(author, source_id)["resource"]
    manifest = function_execution.manifest()
    for field in (
        "implementation_id",
        "determinism",
        "code_sha256",
        "dependency_sha256",
    ):
        if source["attributes"]["definition"][field] != manifest[field]:
            raise ValueError(
                "Republish the source-account Function for the settled runtime first"
            )
    downstream = publish(
        author,
        reviewer,
        "FunctionDefinition",
        FUNCTION_KEY,
        "Labels from retained source account objects",
        {
            "object_set_id": source["attributes"]["object_set_id"],
            "definition": {
                **{
                    field: manifest[field]
                    for field in (
                        "implementation_id",
                        "determinism",
                        "code_sha256",
                        "dependency_sha256",
                    )
                },
                "derived_property_ids": [DERIVED_PROPERTY],
            },
        },
    )
    transformation = publish(
        author,
        reviewer,
        "TransformationDefinition",
        KEY,
        "Source account retained-input chain",
        {
            "resource_budget": {
                "max_returned_rows": 6,
                "max_derived_evaluations": 6,
                "max_published_result_bytes": 1000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source_accounts",
                        "function_id": str(source_id),
                        "offset": 0,
                        "limit": 3,
                    },
                    {
                        "node_id": "retained_labels",
                        "function_id": downstream["resource_id"],
                        "offset": 0,
                        "limit": 3,
                        "depends_on": ["source_accounts"],
                        "input_binding": {"upstream_node_id": "source_accounts"},
                    },
                ],
                "outputs": [
                    {"output_id": "source_accounts", "node_id": "source_accounts"},
                    {"output_id": "retained_labels", "node_id": "retained_labels"},
                ],
            },
        },
    )
    print(
        json.dumps(
            {
                "transformation": transformation["resource_id"],
                "version_id": transformation["version_id"],
                "prepared_only": True,
            }
        )
    )


def verify_chain(client, result):
    assert result["business_effect_authorized"] is False
    assert result["current_use_authorized"] is False
    compiled = result["request"]["compiled_plan"]
    assert compiled["node_order"] == ["source_accounts", "retained_labels"]
    assert len(result["publications"]) == 1
    publication = result["publications"][0]
    assert publication["authority"] == "EXECUTION_ONLY"
    outputs = {output["slot"]: output["value"] for output in publication["outputs"]}
    assert set(outputs) == {"source_accounts", "retained_labels"}
    invocations = {}
    for slot, reference in outputs.items():
        response = client.get(f"/functions/invocations/{reference['invocation_id']}")
        response.raise_for_status()
        invocation = response.json()
        assert invocation["status"] == "SUCCEEDED"
        assert invocation["receipt_hash"] == reference["receipt_hash"]
        assert invocation["output"]["run_id"] == reference["run_id"]
        assert invocation["output"]["mode"] == "EVIDENCE_ANALYSIS_ONLY"
        assert invocation["output"]["business_effect_authorized"] is False
        assert invocation["output"]["current_use_authorized"] is False
        invocations[slot] = invocation
    upstream, downstream = (
        invocations["source_accounts"],
        invocations["retained_labels"],
    )

    def pins(invocation):
        return [
            {
                field: obj[field]
                for field in ("resource_id", "version_id", "content_hash")
            }
            for obj in invocation["output"]["objects"]
        ]

    assert len(pins(upstream)) == 3 and pins(upstream) == pins(downstream)
    assert (
        upstream["output"]["query"]["known_at"]
        == downstream["output"]["query"]["known_at"]
    )
    assert (
        upstream["output"]["query"]["valid_at"]
        == downstream["output"]["query"]["valid_at"]
    )
    assert downstream["output"]["input_result"] == {
        "invocation_id": upstream["invocation_id"],
        "receipt_hash": upstream["receipt_hash"],
        "run_id": upstream["output"]["run_id"],
    }
    assert downstream["output"]["coverage"] == "RETAINED_INPUT_PAGE_ONLY"
    assert downstream["output"]["objects"] == upstream["output"]["objects"]
    assert downstream["output"]["query"] == upstream["output"]["query"]
    assert len(downstream["output"]["derived_values"]) == 3
    assert all(
        value["status"] == "AVAILABLE"
        for value in downstream["output"]["derived_values"]
    )
    return {
        "invocations": invocations,
        "exact_input_object_pins": pins(upstream),
        "input_receipt_and_object_versions_verified": True,
        "mid_step_crash_recovery_demonstrated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--replay", action="store_true")
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/development/evidence/nin12-transformation-retained-input.json"
        ),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    required = (
        {"ontology_admin", "ontology_propose", "ontology_read"}
        if args.prepare
        else {"read", "ontology_read", "ingest"}
    )
    token, author = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if required.issubset(grant["permissions"])
    )
    identity = canonical_id(author.scope.tenant_id, "TransformationDefinition", KEY)
    if args.prepare:
        reviewer = next(
            Principal.model_validate(grant)
            for grant in grants.values()
            if grant["actor_id"] != author.actor_id
            and grant["scope"]["tenant_id"] == str(author.scope.tenant_id)
            and {"ontology_admin", "ontology_review"}.issubset(grant["permissions"])
        )
        prepare(author, reviewer)
        return
    previous = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.replay or args.read_only
        else None
    )
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": "Bearer " + token}, timeout=60,
        trust_env=False, follow_redirects=False,
    ) as client:
        if previous:
            request = previous["request"]
        else:
            response = client.get(f"/resources/{identity}")
            response.raise_for_status()
            now = datetime.now(UTC).isoformat()
            request = {
                "request_id": str(uuid4()),
                "transformation": {
                    "resource_id": str(identity),
                    "version_id": response.json()["resource"]["version_id"],
                },
                "valid_at": now,
                "known_at": now,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({"phase": "REQUEST_PREPARED", "request": request}, indent=2)
                + "\n",
                encoding="utf-8",
            )
        if not args.read_only:
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
            assert (
                response.json()["workflow_id"]
                == "transformation:" + request["request_id"]
            )
        result = shared.read_complete(client, request["request_id"], args.timeout)
        proof = verify_chain(client, result)
        if not args.read_only:
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
            assert response.json()["workflow_id"] == result["workflow_id"]
        repeated = shared.read_complete(client, request["request_id"], args.timeout)
        assert shared.retained_part(repeated) == shared.retained_part(result)
        if previous and previous.get("result"):
            assert shared.retained_part(previous["result"]) == shared.retained_part(
                result
            )
    args.output.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "request": request,
                "result": result,
                "chain": proof,
                "retained_repeat_and_history_equal": True,
                "financial_authority_established": False,
                "read_only_verification": args.read_only,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Retained source-account input chain verified; exact object versions and history preserved."
    )


if __name__ == "__main__":
    main()

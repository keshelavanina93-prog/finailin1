"""Review and prove an actual source-account Function DAG through the mounted API.

Run --prepare only after the shared Function is republished for the settled package.
The default mode starts a new build; --replay resubmits its retained request;
--read-only verifies the same retained build without submitting any work.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import function_execution, resources, transformation_definitions
from finai_api.services.workspace import WorkspaceError

FUNCTION_KEY = "source-accounts:reviewed-label-analysis:v1"
KEY = "source-accounts:reviewed-page-build:v1"
NODES = ("first_page", "next_page")
OUTPUTS = ("source_accounts_first_page", "source_accounts_next_page")


def prepare(author: Principal, grants: dict, identity: UUID) -> None:
    function_id = canonical_id(
        author.scope.tenant_id, "FunctionDefinition", FUNCTION_KEY
    )
    function = resources.get_resource(author, function_id)["resource"]
    now = datetime.now(UTC)
    function_execution.plan(
        author,
        FunctionInvocation(
            function=VersionReference(
                resource_id=function_id, version_id=function["version_id"]
            ),
            valid_at=now,
            known_at=now,
            limit=3,
        ),
    )
    attributes = {
        "definition": {
            "nodes": [
                {
                    "node_id": NODES[0],
                    "function_id": str(function_id),
                    "offset": 0,
                    "limit": 3,
                },
                {
                    "node_id": NODES[1],
                    "function_id": str(function_id),
                    "depends_on": [NODES[0]],
                    "offset": 3,
                    "limit": 3,
                },
            ],
            "outputs": [
                {"output_id": output, "node_id": node}
                for output, node in zip(OUTPUTS, NODES, strict=True)
            ],
        }
    }
    previous = None
    try:
        previous = resources.get_resource(author, identity)["resource"]
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
    if previous and previous["attributes"] == attributes:
        try:
            transformation_definitions.plan(
                author,
                TransformationRunRequest(
                    transformation=VersionReference(
                        resource_id=identity, version_id=previous["version_id"]
                    ),
                    valid_at=now,
                    known_at=now,
                ),
            )
        except WorkspaceError as exc:
            if exc.status != 409:
                raise
        else:
            print(
                "Reviewed source build already matches the current exact Function pins."
            )
            return
    reviewer = next(
        p
        for value in grants.values()
        if (p := Principal.model_validate(value)).actor_id != author.actor_id
        and p.scope.tenant_id == author.scope.tenant_id
        and {"ontology_admin", "ontology_review"}.issubset(p.permissions)
    )
    proposal = ResourceProposal(
        title="Source account observation build",
        rationale="Run two bounded source-label query pages with explicit completion order and named retained outputs; no accounting activation",
        access_entity=author.scope.legal_entity_id,
        mutations=[
            ResourceMutation(
                resource_id=identity,
                object_type="TransformationDefinition",
                identity_key=KEY,
                display_name="Source account observation build",
                expected_version_id=UUID(previous["version_id"]) if previous else None,
                valid_from=datetime.now(UTC),
                attributes=attributes,
            )
        ],
    )
    resources.propose(author, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independently reviewed exact Function pins and completion barriers; no data-transfer or financial authority assertion",
        ),
    )
    print("Reviewed source build", str(identity), "proposal", str(proposal.proposal_id))


def retained_part(result: dict) -> dict:
    return {
        key: value
        for key, value in result.items()
        if key not in ("runtime_status", "execution")
    }


def read_complete(client: httpx.Client, request_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/transformations/runs/{request_id}")
        response.raise_for_status()
        result = response.json()
        state = result.get("execution", {}).get("state")
        if result.get("publications"):
            return result
        if state in ("FAILED", "CANCELLED") or result.get("runtime_status") in (
            "FAILED",
            "CANCELED",
            "TERMINATED",
            "TIMED_OUT",
        ):
            raise AssertionError(
                f"Source build did not complete: {state or result.get('runtime_status')}"
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Source build has no retained publication before the proof deadline"
            )
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--replay", action="store_true")
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin12-transformation-runtime.json"),
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
        prepare(author, grants, identity)
        return
    previous = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.replay or args.read_only
        else None
    )
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": "Bearer " + token}, timeout=60
    ) as client:
        if previous:
            request = previous["request"]
        else:
            response = client.get(f"/resources/{identity}")
            response.raise_for_status()
            version = response.json()["resource"]["version_id"]
            cutoff = datetime.now(UTC).isoformat()
            request = {
                "request_id": str(uuid4()),
                "transformation": {"resource_id": str(identity), "version_id": version},
                "valid_at": cutoff,
                "known_at": cutoff,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({"phase": "REQUEST_PREPARED", "request": request}, indent=2)
                + "\n",
                encoding="utf-8",
            )
        if not args.read_only:
            started = client.post("/transformations/runs", json=request)
            started.raise_for_status()
            assert (
                started.json()["workflow_id"]
                == "transformation:" + request["request_id"]
            )
        result = read_complete(client, request["request_id"], args.timeout)
        assert result["business_effect_authorized"] is False
        assert result["current_use_authorized"] is False
        compiled = result["request"]["compiled_plan"]
        assert compiled["node_order"] == list(NODES)
        assert compiled["dependency_semantics"] == "COMPLETION_BARRIER_ONLY"
        assert compiled["coverage"] == "DECLARED_QUERY_PAGES_ONLY"
        assert (
            compiled["transformation"]["version_id"]
            == request["transformation"]["version_id"]
        )
        assert len(result["publications"]) == 1
        publication = result["publications"][0]
        assert publication["authority"] == "EXECUTION_ONLY"
        assert {output["slot"] for output in publication["outputs"]} == set(OUTPUTS)
        events = {event["event_id"]: event for event in result["events"]}
        first_done = events[f"node:{NODES[0]}:terminal"]
        next_started = events[f"node:{NODES[1]}:started"]
        assert datetime.fromisoformat(
            first_done["created_at"]
        ) <= datetime.fromisoformat(next_started["created_at"])
        node_results = []
        object_ids = set()
        for output in publication["outputs"]:
            reference = output["value"]
            response = client.get(
                f"/functions/invocations/{reference['invocation_id']}"
            )
            response.raise_for_status()
            invocation = response.json()
            assert invocation["status"] == "SUCCEEDED"
            assert invocation["receipt_hash"] == reference["receipt_hash"]
            assert invocation["output"]["run_id"] == reference["run_id"]
            assert len(invocation["output"]["objects"]) == 3
            assert len(invocation["output"]["derived_values"]) == 3
            assert all(
                value["status"] == "AVAILABLE"
                for value in invocation["output"]["derived_values"]
            )
            assert invocation["output"]["mode"] == "EVIDENCE_ANALYSIS_ONLY"
            object_ids.update(
                obj["resource_id"] for obj in invocation["output"]["objects"]
            )
            node_results.append({"output_id": output["slot"], "invocation": invocation})
        assert len(object_ids) == 6
        if not args.read_only:
            repeated = client.post("/transformations/runs", json=request)
            repeated.raise_for_status()
            assert (
                repeated.json()["workflow_id"]
                == "transformation:" + request["request_id"]
            )
        repeated_result = read_complete(client, request["request_id"], args.timeout)
        assert retained_part(repeated_result) == retained_part(result)
        if previous and previous.get("result"):
            assert retained_part(previous["result"]) == retained_part(result)
    args.output.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "request": request,
                "result": result,
                "named_outputs": node_results,
                "retained_repeat_and_history_equal": True,
                "completion_barrier_verified": True,
                "replayed_existing_intent": args.replay,
                "read_only_verification": args.read_only,
                "financial_authority_established": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Actual source build: two completed Function nodes, six observations, two named outputs; history unchanged."
    )


if __name__ == "__main__":
    main()

"""Review stale active source references without weakening retained evidence history."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import function_execution, resources
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "historical_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
KEY = "sog-source-contexts:parallel-function-build:v1"
SOURCES = {
    "region": "7959af7f-a1bb-5573-8006-d1fc14f58681",
    "department": "2bd64825-e320-5039-b163-2064a1a71c82",
}
PRIOR = {
    "region": "nin6-calculated-binding-runtime.json",
    "department": "nin12-transformation-binding-runtime.json",
}
UNCHANGED = (
    "resource_id",
    "identity_key",
    "object_type",
    "display_name",
    "attributes",
    "evidence_class",
    "access_entity",
    "authority_state",
)


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def assert_active_refusal(principal, source):
    with (
        resources.resource_connection(principal) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        try:
            upstream_authority(
                cursor,
                principal.scope.tenant_id,
                UUID(source["version_id"]),
                allow_historical_provenance=True,
            )
        except WorkspaceError as exc:
            assert exc.status == 409 and "unavailable" in exc.detail.lower()
            return {"source": pin(source), "status": exc.status, "reason": exc.detail}
    raise AssertionError(
        "An old ACTIVE source reference unexpectedly became current-use eligible"
    )


def catalog(client):
    result = {}
    after = None
    for _ in range(20):
        response = client.get(
            "/functions", params={"after_resource_id": after} if after else {}
        )
        response.raise_for_status()
        page = response.json()
        result.update({row["reference"]["resource_id"]: row for row in page["items"]})
        after = page["next_cursor"]
        if after is None:
            return result
    raise AssertionError("Bounded Function catalog traversal exceeded its page limit")


def prepare_build(author, reviewer):
    manifest = function_execution.manifest()
    definition = {
        **{
            key: manifest[key]
            for key in (
                "implementation_id",
                "determinism",
                "code_sha256",
                "dependency_sha256",
            )
        },
        "derived_property_ids": [],
    }
    sets, functions = {}, {}
    for node, identity in SOURCES.items():
        sets[node] = shared.publish(
            author,
            reviewer,
            "ObjectSetDefinition",
            KEY + ":" + node,
            "Original SOG source context: " + node,
            {
                "definition": {
                    "object_type": "CompanyDimension",
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
            {"object_set_id": sets[node]["resource_id"], "definition": definition},
        )
    functions["joined"] = shared.publish(
        author,
        reviewer,
        "FunctionDefinition",
        KEY + ":joined",
        "Inspect retained Region after both source reads",
        {"object_set_id": sets["region"]["resource_id"], "definition": definition},
    )
    nodes = [
        {
            "node_id": node,
            "function_id": functions[node]["resource_id"],
            "offset": 0,
            "limit": 1,
        }
        for node in SOURCES
    ]
    nodes.append(
        {
            "node_id": "joined",
            "function_id": functions["joined"]["resource_id"],
            "offset": 0,
            "limit": 1,
            "depends_on": list(SOURCES),
            "input_binding": {"upstream_node_id": "region"},
        }
    )
    transform = shared.publish(
        author,
        reviewer,
        "TransformationDefinition",
        KEY,
        "Parallel Region and Department reads with retained-input dependency",
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
        "functions": {key: pin(row) for key, row in functions.items()},
        "transformation": pin(transform),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in (
        "prepare-source-review",
        "approve-source-review",
        "prepare-build",
        "start",
        "readback",
    ):
        modes.add_argument("--" + name, action="store_true")
    parser.add_argument(
        "--request-id",
        help="Adopt an existing browser-started build with its exact frozen request",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8062/v1/ontology")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "docs/development/evidence/nin12-historical-provenance-runtime.json"
        ),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    author = next(
        Principal.model_validate(g)
        for g in grants.values()
        if {"ontology_admin", "ontology_propose", "ontology_read"}.issubset(
            g["permissions"]
        )
    )
    reviewer = next(
        Principal.model_validate(g)
        for g in grants.values()
        if g["actor_id"] != author.actor_id
        and g["scope"]["tenant_id"] == str(author.scope.tenant_id)
        and {"ontology_admin", "ontology_review"}.issubset(g["permissions"])
    )
    token, reader = next(
        (t, Principal.model_validate(g))
        for t, g in grants.items()
        if {"read", "ingest", "ontology_read"}.issubset(g["permissions"])
    )
    proof = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.output.exists()
        else {}
    )
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + token},
        timeout=90,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        if args.prepare_source_review:
            if proof:
                assert proof["phase"] == "SOURCE_REVIEW_PREPARED"
                proposal = ResourceProposal.model_validate(proof["proposal"])
                try:
                    detail = resources.proposal_detail(author, proposal.proposal_id)
                except WorkspaceError as exc:
                    if exc.status != 404:
                        raise
                    detail = resources.propose(author, proposal)
                assert detail.proposal.model_dump(mode="json") == proof["proposal"]
                proof["proposal_detail"] = detail.model_dump(mode="json")
            else:
                before, targets, mutations = {}, {}, []
                for node, identity in SOURCES.items():
                    before[node] = resources.get_resource(author, UUID(identity))[
                        "resource"
                    ]
                    original = json.loads(
                        (ROOT / "docs/development/evidence" / PRIOR[node]).read_text(
                            encoding="utf-8"
                        )
                    )
                    assert all(
                        before[node][key] == original["prepared"]["source"][key]
                        for key in UNCHANGED
                    )
                    assert pin(before[node]) == pin(original["prepared"]["source"])
                    target = resources.get_resource(
                        author, UUID(before[node]["attributes"]["dimension_id"])
                    )["resource"]
                    assert target["authority_state"] == "APPROVED"
                    assert pin(target) == pin(original["published_target"])
                    assert (
                        target["attributes"]
                        == original["prepared"]["target"]["attributes"]
                    )
                    assert (
                        target["resource_id"]
                        == original["prepared"]["target"]["resource_id"]
                    )
                    targets[node] = target
                    mutations.append(
                        ResourceMutation(
                            **{key: before[node][key] for key in UNCHANGED},
                            expected_version_id=before[node]["version_id"],
                            valid_from=datetime.now(UTC),
                            valid_to=before[node]["valid_to"],
                        )
                    )
                proposal = ResourceProposal(
                    title="Revalidate two unchanged source contexts against reviewed dimension versions",
                    rationale="Preserve original source facts, identities and evidence; revalidate active dimension references after independent display-only target reviews. Historical provenance remains retained and grants no financial authority.",
                    access_entity=author.scope.legal_entity_id,
                    mutations=mutations,
                )
                proof = {
                    "phase": "SOURCE_REVIEW_PREPARED",
                    "before": before,
                    "targets": targets,
                    "active_refusals_before": [
                        assert_active_refusal(reader, row) for row in before.values()
                    ],
                    "catalog_before": catalog(client),
                    "proposal": proposal.model_dump(mode="json"),
                }
                save(args.output, proof)
                detail = resources.propose(author, proposal)
                proof["proposal_detail"] = detail.model_dump(mode="json")
            save(args.output, proof)
        elif args.approve_source_review:
            resources.review(
                reviewer,
                UUID(proof["proposal"]["proposal_id"]),
                ResourceReview(
                    decision="APPROVED",
                    rationale="Independently reviewed unchanged source values and canonical identities; active references now bind existing reviewed dimension versions.",
                ),
            )
            after = {
                node: resources.get_resource(author, UUID(identity))["resource"]
                for node, identity in SOURCES.items()
            }
            with (
                resources.resource_connection(reader) as conn,
                conn.cursor(row_factory=dict_row) as cursor,
            ):
                for node, row in after.items():
                    assert all(
                        row[key] == proof["before"][node][key] for key in UNCHANGED
                    )
                    assert row["version_id"] != proof["before"][node]["version_id"]
                    edge = cursor.execute(
                        "SELECT target_resource_id,target_version_id FROM resource_dependencies WHERE tenant_id=%s AND version_id=%s AND relation='FIELD:dimension_id'",
                        (reader.scope.tenant_id, row["version_id"]),
                    ).fetchone()
                    assert (
                        str(edge["target_version_id"])
                        == proof["targets"][node]["version_id"]
                    )
            proof.update(after=after, phase="SOURCE_REFERENCES_REVIEWED")
        elif args.prepare_build:
            assert proof.get("after")
            proof.update(build=prepare_build(author, reviewer), phase="BUILD_PREPARED")
        else:
            request = proof.get("request")
            if args.request_id:
                response = client.get("/transformations/runs/" + args.request_id)
                response.raise_for_status()
                adopted = response.json()["request"]["compiled_plan"]["request"]
                assert adopted["request_id"] == args.request_id
                assert adopted["transformation"] == proof["build"]["transformation"]
                if request is not None:
                    assert request == adopted
                request = adopted
                proof["request"] = request
                save(args.output, proof)
            if request is None:
                assert args.start
                now = datetime.now(UTC).isoformat()
                request = {
                    "request_id": str(uuid4()),
                    "transformation": proof["build"]["transformation"],
                    "valid_at": now,
                    "known_at": now,
                }
                proof["request"] = request
                save(args.output, proof)
            available = catalog(client)
            assert all(
                available[ref["resource_id"]]["reference"] == ref
                for ref in proof["build"]["functions"].values()
            )
            if args.start:
                response = client.post("/transformations/runs", json=request)
                response.raise_for_status()
            result = shared.shared.read_complete(client, request["request_id"], 120)
            assert len(result["publications"]) == 1
            invocations = {}
            for output in result["publications"][0]["outputs"]:
                ref = output["value"]
                response = client.get("/functions/invocations/" + ref["invocation_id"])
                response.raise_for_status()
                receipt = response.json()
                assert (
                    receipt["status"] == "SUCCEEDED"
                    and receipt["receipt_hash"] == ref["receipt_hash"]
                )
                assert receipt["output"]["run_id"] == ref["run_id"]
                invocations[output["slot"]] = receipt
            compiled_nodes = {
                node["node_id"]: node
                for node in result["request"]["compiled_plan"]["nodes"]
            }
            for node, receipt in invocations.items():
                output = receipt["output"]
                assert (
                    output["retained_provenance_authority"]
                    == compiled_nodes[node]["function_plan"][
                        "retained_provenance_authority"
                    ]
                )
                assert output["current_use_authorized"] is False
                assert output["business_effect_authorized"] is False
            for node in SOURCES:
                authority = {
                    row["version_id"]: row["lineage_use"]
                    for row in invocations[node]["output"][
                        "retained_provenance_authority"
                    ]
                }
                original = json.loads(
                    (ROOT / "docs/development/evidence" / PRIOR[node]).read_text(
                        encoding="utf-8"
                    )
                )
                assert authority[proof["before"][node]["version_id"]] == "HISTORICAL"
                assert (
                    authority[original["prepared"]["target"]["version_id"]]
                    == "HISTORICAL"
                )
                assert authority[proof["after"][node]["version_id"]] == "ACTIVE"
                assert authority[proof["targets"][node]["version_id"]] == "ACTIVE"
                obj = invocations[node]["output"]["objects"][0]
                assert pin(obj) == pin(proof["after"][node])
                assert obj["attributes"] == proof["before"][node]["attributes"]
            source = invocations["region"]
            joined = invocations["joined"]["output"]
            assert joined["objects"] == source["output"]["objects"]
            assert joined["input_result"] == {
                "invocation_id": source["invocation_id"],
                "receipt_hash": source["receipt_hash"],
                "run_id": source["output"]["run_id"],
            }
            proof["invocations"] = invocations
            proof["frozen_provenance_and_active_historical_roles_verified"] = True
            if proof.get("result"):
                assert shared.shared.retained_part(
                    proof["result"]
                ) == shared.shared.retained_part(result)
            proof.update(
                result=result,
                catalog_after=available,
                phase="EVIDENCE_BUILD_VERIFIED",
                active_refusals_after=[
                    assert_active_refusal(reader, row)
                    for row in proof["before"].values()
                ],
            )
        # Existing completed binding/source receipts stay historical and readable.
        retained_receipts = {}
        for node, filename in PRIOR.items():
            prior = json.loads(
                (ROOT / "docs/development/evidence" / filename).read_text(
                    encoding="utf-8"
                )
            )
            original = prior["invocation"]
            exact_scope = original["receipt"]["exact_scope"]
            # History envelopes omit actor_id; resolve it from the retained invocation
            # under the existing administrator grant and the receipt's unchanged scope.
            assert author.scope.model_dump(mode="json") == exact_scope
            with (
                resources.resource_connection(author) as conn,
                conn.cursor(row_factory=dict_row) as cursor,
            ):
                conn.execute(
                    "SELECT set_config('finai.exact_scope',%s,true)",
                    (json.dumps(exact_scope),),
                )
                owner = cursor.execute(
                    "SELECT actor_id FROM function_invocations WHERE tenant_id=%s AND request_id=%s",
                    (author.scope.tenant_id, original["invocation_id"]),
                ).fetchone()
            assert owner is not None, "Retained invocation owner is unavailable"
            original_token = next(
                t
                for t, grant in grants.items()
                if grant["scope"] == exact_scope
                and grant["actor_id"] == owner["actor_id"]
                and "ontology_read" in grant["permissions"]
            )
            response = client.get(
                "/functions/invocations/" + original["invocation_id"],
                headers={"Authorization": "Bearer " + original_token},
            )
            response.raise_for_status()
            assert response.json() == original
            retained_receipts[node] = original["receipt_hash"]
        proof["original_receipts_unchanged"] = retained_receipts
    save(
        args.output,
        {
            **proof,
            "checked_at": datetime.now(UTC).isoformat(),
            "financial_authority_established": False,
            "strict_authority_or_certification_granted": False,
        },
    )
    print(proof["phase"])


if __name__ == "__main__":
    main()

"""Verify packaged worker execution with separately reviewed validation Functions."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "shared_build_proof", ROOT / "scripts/verify-transformation-runtime.py"
)
shared = importlib.util.module_from_spec(loader)
loader.loader.exec_module(shared)
KEY = "packaged-validation:sog-grouped-observation-chain:v1"
FUNCTION_KEY = "packaged-validation:sog-grouped-observation-counts:v1"
OBJECT_SET = "72f56d81-f99f-5ccd-a5b8-64af9d284409"
FIELDS = ["posting_date", "unit_status"]
SOURCE_HASH = "45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d"
EVIDENCE = "71f45f39-35fb-56c1-b4b7-61e7edc56368"


def publish(client, review_client, author, kind, key, title, attributes):
    identity = canonical_id(author.scope.tenant_id, kind, key)
    response = client.get(f"/resources/{identity}")
    if response.status_code == 404:
        previous = None
    else:
        response.raise_for_status()
        previous = response.json()["resource"]
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
    response = client.post("/proposals", json=proposal.model_dump(mode="json"))
    response.raise_for_status()
    response = review_client.post(
        f"/proposals/{proposal.proposal_id}/decision",
        json=ResourceReview(
            decision="APPROVED",
            rationale="Independent review of packaged validation execution over unchanged source identities",
        ).model_dump(mode="json"),
    )
    response.raise_for_status()
    response = client.get(f"/resources/{identity}")
    response.raise_for_status()
    return response.json()["resource"]


def prepare(client, review_client, author):
    response = client.get("/functions/implementation")
    response.raise_for_status()
    manifest = response.json()
    implementation = {
        field: manifest[field]
        for field in (
            "implementation_id",
            "determinism",
            "code_sha256",
            "dependency_sha256",
        )
    }
    source = publish(
        client,
        review_client,
        author,
        "FunctionDefinition",
        "packaged-validation:sog-posting-date-query:v1",
        "Packaged validation: source window",
        {
            "object_set_id": OBJECT_SET,
            "definition": {**implementation, "derived_property_ids": []},
        },
    )
    source_id = source["resource_id"]
    downstream = publish(
        client,
        review_client,
        author,
        "FunctionDefinition",
        FUNCTION_KEY,
        "SOG posting-date and unit-status observation counts",
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
                "derived_property_ids": [],
                "group_count": {
                    "schema_id": str(
                        canonical_id(
                            author.scope.tenant_id,
                            "SchemaDefinition",
                            "SourceJournalMovement",
                        )
                    ),
                    "fields": FIELDS,
                },
            },
        },
    )
    transformation = publish(
        client,
        review_client,
        author,
        "TransformationDefinition",
        KEY,
        "SOG retained-window observation counts",
        {
            "resource_budget": {
                "max_returned_rows": 400,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 1000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source_window",
                        "function_id": str(source_id),
                        "offset": 0,
                        "limit": 200,
                    },
                    {
                        "node_id": "observation_counts",
                        "function_id": downstream["resource_id"],
                        "offset": 0,
                        "limit": 200,
                        "depends_on": ["source_window"],
                        "input_binding": {"upstream_node_id": "source_window"},
                    },
                ],
                "outputs": [
                    {"output_id": "source_window", "node_id": "source_window"},
                    {
                        "output_id": "observation_counts",
                        "node_id": "observation_counts",
                    },
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
    assert len(result["publications"]) == 1
    publication = result["publications"][0]
    assert publication["authority"] == "EXECUTION_ONLY"
    outputs = {item["slot"]: item["value"] for item in publication["outputs"]}
    assert set(outputs) == {"source_window", "observation_counts"}
    invocations = {}
    for slot, reference in outputs.items():
        response = client.get(f"/functions/invocations/{reference['invocation_id']}")
        response.raise_for_status()
        invocation = response.json()
        assert invocation["status"] == "SUCCEEDED"
        assert invocation["receipt_hash"] == reference["receipt_hash"]
        assert invocation["output"]["run_id"] == reference["run_id"]
        assert invocation["output"]["business_effect_authorized"] is False
        assert invocation["output"]["current_use_authorized"] is False
        invocations[slot] = invocation
    upstream, downstream = (
        invocations["source_window"],
        invocations["observation_counts"],
    )
    rows = upstream["output"]["objects"]
    assert rows and rows == downstream["output"]["objects"]
    assert upstream["output"]["query"] == downstream["output"]["query"]
    assert downstream["output"]["input_result"] == {
        "invocation_id": outputs["source_window"]["invocation_id"],
        "receipt_hash": upstream["receipt_hash"],
        "run_id": upstream["output"]["run_id"],
    }
    counts = downstream["output"]["group_counts"]
    assert counts["contract"] == "grouped-observation-counts/1"
    assert counts["authority"] == "OBSERVATION_COUNTS_ONLY"
    assert counts["coverage"] == "COMPLETE_BOUNDED_OBJECT_SET"
    assert counts["fields"] == FIELDS and counts["object_count"] == len(rows)
    compiled_nodes = result["request"]["compiled_plan"]["nodes"]
    count_node = next(
        node for node in compiled_nodes if node["node_id"] == "observation_counts"
    )
    assert counts["schema"] == count_node["function_plan"]["group_count"]["schema"]
    assert sum(group["count"] for group in counts["groups"]) == len(rows)
    pins = lambda values: sorted(
        (item["resource_id"], item["version_id"], item["content_hash"])
        for item in values
    )
    contributors = [
        item for group in counts["groups"] for item in group["contributors"]
    ]
    assert pins(contributors) == pins(rows)
    by_version = {row["version_id"]: row for row in rows}
    for group in counts["groups"]:
        assert group["count"] == len(group["contributors"])
        for contributor in group["contributors"]:
            row = by_version[contributor["version_id"]]
            expected = [
                {"field": field, "state": "VALUE", "value": row["attributes"][field]}
                for field in FIELDS
            ]
            assert group["key"] == expected
            assert row["attributes"]["unit_status"] == "UNESTABLISHED"
            assert row["attributes"]["posting_date"] == "2025-11-03"
            assert row["schema_version_id"] == counts["schema"]["version_id"]
    known_at = upstream["output"]["query"]["known_at"]
    evidence_bindings = []
    for row in rows:
        assert row["evidence_class"] == "SOURCE_BOUND"
        response = client.get(
            f"/operator/trace/{row['resource_id']}",
            params={"version_id": row["version_id"], "known_at": known_at},
        )
        response.raise_for_status()
        trace = response.json()
        edges = [
            edge
            for edge in trace["edges"]
            if edge["source_version_id"] == row["version_id"]
            and edge["relation"] == "FIELD:evidence_id"
        ]
        assert len(edges) == 1
        evidence_version = edges[0]["target_version_id"]
        response = client.get(
            f"/operator/resources/{EVIDENCE}",
            params={"version_id": evidence_version, "known_at": known_at},
        )
        response.raise_for_status()
        evidence = response.json()["resource"]
        assert (
            evidence["resource_id"] == EVIDENCE
            and evidence["version_id"] == evidence_version
        )
        assert evidence["attributes"]["sha256"] == SOURCE_HASH
        evidence_bindings.append(
            {
                "object_version_id": row["version_id"],
                "evidence": {
                    key: evidence[key]
                    for key in ("resource_id", "version_id", "content_hash")
                },
            }
        )
    return {
        "invocations": invocations,
        "source_evidence_bindings": evidence_bindings,
        "count_conservation_verified": True,
        "exact_contributors_verified": True,
        "mid_step_crash_recovery_demonstrated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--replay", action="store_true")
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin31-packaged-worker-runtime.json"),
    )
    args = parser.parse_args()
    destination = urlsplit(args.base_url)
    if (
        destination.scheme != "http"
        or destination.hostname not in {"127.0.0.1", "localhost"}
        or destination.username is not None
        or destination.password is not None
        or destination.query
        or destination.fragment
        or destination.path.rstrip("/") != "/v1/ontology"
    ):
        parser.error("Candidate API must be an explicit local /v1/ontology endpoint")
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
        reviewer_token = next(
            token
            for token, grant in grants.items()
            if grant["actor_id"] != author.actor_id
            and grant["scope"]["tenant_id"] == str(author.scope.tenant_id)
            and {"ontology_admin", "ontology_review"}.issubset(grant["permissions"])
        )
        with (
            httpx.Client(
                base_url=args.base_url,
                headers={"Authorization": "Bearer " + token},
                timeout=60,
                trust_env=False,
                follow_redirects=False,
            ) as client,
            httpx.Client(
                base_url=args.base_url,
                headers={"Authorization": "Bearer " + reviewer_token},
                timeout=60,
                trust_env=False,
                follow_redirects=False,
            ) as review_client,
        ):
            prepare(client, review_client, author)
        return
    previous = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.replay or args.read_only
        else None
    )
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + token},
        timeout=60,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        response = client.get("/functions/implementation")
        response.raise_for_status()
        candidate_manifest = response.json()
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
        assert len(proof["source_evidence_bindings"]) == 2
        for invocation in proof["invocations"].values():
            for field in ("implementation_id", "code_sha256", "dependency_sha256"):
                assert (
                    invocation["output"]["implementation"][field]
                    == candidate_manifest[field]
                )
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
                "candidate_api": args.base_url,
                "candidate_manifest": candidate_manifest,
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
        "Authentic grouped observation counts verified; no financial aggregation or established unit."
    )


if __name__ == "__main__":
    main()

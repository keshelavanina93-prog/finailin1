"""Verify a reviewed source-record interface over authentic retained observations."""

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
    "interface_proof_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(loader)
loader.loader.exec_module(shared)
KEY = "retained-observations:source-record-interface:v1"
SEMANTIC = "5d336b77-e7fd-5aaf-996e-29f8ceac7fc7"
CASES = {
    "00c93da8-3ab9-5597-aaf6-ea79b7307d32": {
        "type": "SourceAccountDefinition",
        "schema": "e365d1cd-40f1-5fa5-8343-3db93f32e4aa",
        "record": "fffbaa02-cda2-54d7-bbcc-fe5bf70d95a3",
        "evidence": "0074068a-99ea-5a03-8e61-15f7430b04d4",
        "sha256": "607e37da8aa8e05687c9898cc1577db070c082ece8281c7bd3a43e725aac73df",
    },
    "01603366-ac6b-5871-b56e-0b1703b52241": {
        "type": "SourceJournalMovement",
        "schema": "bad94aa4-a02c-56fb-bc85-63e51e5b2282",
        "record": "830aa111-3c59-5fac-887b-47700a24b842",
        "evidence": "71f45f39-35fb-56c1-b4b7-61e7edc56368",
        "sha256": "45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d",
    },
}


def pin(resource):
    return {key: resource[key] for key in ("resource_id", "version_id")}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def prepare(author, reviewer):
    interface = shared.publish(
        author,
        reviewer,
        "ObjectInterface",
        KEY,
        "Retained observations with source records",
        {
            "definition": {
                "fields": {
                    "source_record": {
                        "kind": "reference",
                        "required": True,
                        "semantic_id": SEMANTIC,
                        "target_type": "SourceRecord",
                    },
                    "evidence": {
                        "kind": "reference",
                        "required": False,
                        "semantic_id": SEMANTIC,
                        "target_type": "SourceEvidence",
                    },
                }
            }
        },
    )
    implementations = []
    for case in CASES.values():
        implementations.append(
            shared.publish(
                author,
                reviewer,
                "ObjectTypeImplementation",
                KEY + ":" + case["type"],
                "Source-record interface: " + case["type"],
                {
                    "interface_id": interface["resource_id"],
                    "schema_id": case["schema"],
                    "definition": {
                        "fields": {
                            "source_record": "source_record_id",
                            "evidence": "evidence_id",
                        }
                    },
                },
            )
        )
    query = {
        "object_type": "ObjectInterface",
        "resource_ids": sorted(CASES),
        "interface": {
            **pin(interface),
            "implementations": [pin(x) for x in implementations],
        },
    }
    object_set = shared.publish(
        author,
        reviewer,
        "ObjectSetDefinition",
        KEY,
        "Two retained source observations through their shared interface",
        {"definition": query},
    )
    manifest = function_execution.manifest()
    function = shared.publish(
        author,
        reviewer,
        "FunctionDefinition",
        KEY,
        "Read retained observations through their reviewed interface",
        {
            "object_set_id": object_set["resource_id"],
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
                "derived_property_ids": [],
            },
        },
    )
    return {
        "interface": pin(interface),
        "implementations": [pin(x) for x in implementations],
        "object_set": pin(object_set),
        "function": pin(function),
        "query": query,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--replay", action="store_true")
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin6-interface-query-runtime.json"),
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
    requests = previous.get("requests")
    if requests is None:
        assert not (args.replay or args.read_only), (
            "No retained invocation request to replay"
        )
        now = datetime.now(UTC).isoformat()
        upstream = {
            "request_id": str(uuid4()),
            "function": prepared["function"],
            "valid_at": now,
            "known_at": now,
            "offset": 0,
            "limit": 2,
        }
        downstream = {
            **upstream,
            "request_id": str(uuid4()),
            "input_result": {"invocation_id": upstream["request_id"]},
        }
        requests = [upstream, downstream]
        save(
            args.output,
            {"phase": "REQUEST_PREPARED", "prepared": prepared, "requests": requests},
        )
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": "Bearer " + token}, timeout=90
    ) as client:

        def query(extra=None):
            response = client.post(
                "/object-sets/query",
                json={
                    **prepared["query"],
                    "valid_at": requests[0]["valid_at"],
                    "known_at": requests[0]["known_at"],
                    "limit": 10,
                    **(extra or {}),
                },
            )
            response.raise_for_status()
            return response.json()

        result = query()
        assert result["total"] == 2 and result["next_offset"] is None
        assert {obj["resource_id"] for obj in result["objects"]} == set(CASES)
        assert result["interface_bindings"]
        assert len(result["interface_values"]) == 2
        for projected in result["interface_values"]:
            case = CASES[projected["object_id"]]
            assert projected["status"] == "AVAILABLE"
            assert projected["values"] == {
                "source_record": case["record"],
                "evidence": case["evidence"],
            }
            obj = next(
                x
                for x in result["objects"]
                if x["resource_id"] == projected["object_id"]
            )
            assert projected["object_version_id"] == obj["version_id"]
        for obj in result["objects"]:
            case = CASES[obj["resource_id"]]
            assert (
                obj["object_type"] == case["type"]
                and obj["evidence_class"] == "SOURCE_BOUND"
            )
            assert obj["attributes"]["source_record_id"] == case["record"]
            assert obj["attributes"]["evidence_id"] == case["evidence"]
        filtered = query(
            {
                "filters": [
                    {
                        "field": "evidence",
                        "value": next(iter(CASES.values()))["evidence"],
                    }
                ]
            }
        )
        assert [obj["resource_id"] for obj in filtered["objects"]] == [
            next(iter(CASES))
        ]
        traversed = query(
            {
                "traversal": [
                    {
                        "kind": "reference",
                        "name": "source_record",
                        "direction": "outgoing",
                    }
                ]
            }
        )
        assert traversed["total"] == 2
        assert traversed["interface_values"] == []
        assert {obj["resource_id"] for obj in traversed["objects"]} == {
            c["record"] for c in CASES.values()
        }
        evidence = []
        for obj in result["objects"]:
            response = client.get(
                f"/operator/trace/{obj['resource_id']}",
                params={
                    "version_id": obj["version_id"],
                    "known_at": requests[0]["known_at"],
                },
            )
            response.raise_for_status()
            trace = response.json()
            for field, expected in (
                ("source_record_id", CASES[obj["resource_id"]]["record"]),
                ("evidence_id", CASES[obj["resource_id"]]["evidence"]),
            ):
                edges = [
                    edge
                    for edge in trace["edges"]
                    if edge["source_version_id"] == obj["version_id"]
                    and edge["relation"] == "FIELD:" + field
                ]
                assert len(edges) == 1
                target = next(
                    node
                    for node in trace["nodes"]
                    if node["version_id"] == edges[0]["target_version_id"]
                )
                assert target["resource_id"] == expected
                response = client.get(
                    f"/operator/resources/{expected}",
                    params={
                        "version_id": target["version_id"],
                        "known_at": requests[0]["known_at"],
                    },
                )
                response.raise_for_status()
                exact = response.json()["resource"]
                if field == "source_record_id":
                    selected = next(
                        x for x in traversed["objects"] if x["resource_id"] == expected
                    )
                    assert pin(selected) == pin(exact)
                    assert selected["content_hash"] == exact["content_hash"]
                if field == "evidence_id":
                    assert (
                        exact["attributes"]["sha256"]
                        == CASES[obj["resource_id"]]["sha256"]
                    )
                evidence.append(
                    {
                        "source": pin(obj),
                        "field": field,
                        "target": pin(exact),
                        "content_hash": exact["content_hash"],
                    }
                )
        invocations = []
        for request in requests:
            if not args.read_only:
                response = client.post("/functions/invocations", json=request)
                response.raise_for_status()
            response = client.get(f"/functions/invocations/{request['request_id']}")
            response.raise_for_status()
            invocation = response.json()
            assert invocation["status"] == "SUCCEEDED"
            assert invocation["output"]["objects"] == result["objects"]
            assert (
                invocation["output"]["interface_values"] == result["interface_values"]
            )
            assert (
                invocation["output"]["interface_bindings"]
                == result["interface_bindings"]
            )
            assert invocation["output"]["current_use_authorized"] is False
            assert invocation["output"]["business_effect_authorized"] is False
            invocations.append(invocation)
        assert invocations[1]["output"]["input_result"] == {
            "invocation_id": requests[0]["request_id"],
            "receipt_hash": invocations[0]["receipt_hash"],
            "run_id": invocations[0]["output"]["run_id"],
        }
        assert invocations[1]["output"]["query"] == invocations[0]["output"]["query"]
        assert invocations[1]["output"]["coverage"] == "RETAINED_INPUT_PAGE_ONLY"
        if previous.get("invocations"):
            assert invocations == previous["invocations"]
    save(
        args.output,
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "prepared": prepared,
            "requests": requests,
            "query": result,
            "filtered": filtered,
            "traversal": traversed,
            "exact_provenance": evidence,
            "invocations": invocations,
            "financial_authority_established": False,
            "read_only_verification": args.read_only,
            "replayed_existing_receipts": bool(previous.get("invocations")),
        },
    )
    print(
        "Retained source interface, alias traversal and exact Function input replay verified."
    )


if __name__ == "__main__":
    main()

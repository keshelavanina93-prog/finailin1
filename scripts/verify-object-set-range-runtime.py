"""Verify half-open date selection over retained SOG procurement observations."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.review import Principal
from finai_api.services import function_execution

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "shared_range_proof", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(loader)
loader.loader.exec_module(shared)
SOURCE_HASH = "45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d"
FAMILY = "1c_journal:" + SOURCE_HASH + ":TR"
EVIDENCE = "71f45f39-35fb-56c1-b4b7-61e7edc56368"
SET_KEY = "sog-procurement:posting-date-range:v1"
FUNCTION_KEY = "sog-procurement:posting-date-query:v1"
LOWER, UPPER = "2025-11-03", "2025-11-04"


def filters():
    return [
        {"field": "source_family", "value": FAMILY},
        {"field": "posting_date", "operator": "gte", "value": LOWER},
        {"field": "posting_date", "operator": "lt", "value": UPPER},
    ]


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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
        default=Path("docs/development/evidence/nin6-object-set-range-runtime.json"),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token, principal = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if {"ontology_admin", "ontology_propose", "ontology_read"}.issubset(
            grant["permissions"]
        )
    )
    function_id = canonical_id(
        principal.scope.tenant_id, "FunctionDefinition", FUNCTION_KEY
    )
    if args.prepare:
        reviewer = next(
            Principal.model_validate(grant)
            for grant in grants.values()
            if grant["actor_id"] != principal.actor_id
            and grant["scope"]["tenant_id"] == str(principal.scope.tenant_id)
            and {"ontology_admin", "ontology_review"}.issubset(grant["permissions"])
        )
        selected = shared.publish(
            principal,
            reviewer,
            "ObjectSetDefinition",
            SET_KEY,
            "SOG procurement observations: 3 November 2025",
            {
                "definition": {
                    "object_type": "SourceJournalMovement",
                    "filters": filters(),
                }
            },
        )
        manifest = function_execution.manifest()
        result = shared.publish(
            principal,
            reviewer,
            "FunctionDefinition",
            FUNCTION_KEY,
            "Read SOG procurement posting-date window",
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
                    "derived_property_ids": [],
                },
            },
        )
        print(
            json.dumps(
                {
                    "function_id": result["resource_id"],
                    "function_version": result["version_id"],
                    "object_set": selected["resource_id"],
                    "object_set_version": selected["version_id"],
                    "prepared_only": True,
                }
            )
        )
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
            response = client.get(f"/resources/{function_id}")
            response.raise_for_status()
            now = datetime.now(UTC).isoformat()
            request = {
                "request_id": str(uuid4()),
                "function": {
                    "resource_id": str(function_id),
                    "version_id": response.json()["resource"]["version_id"],
                },
                "valid_at": now,
                "known_at": now,
                "offset": 0,
                "limit": 200,
            }
            save(args.output, {"phase": "REQUEST_PREPARED", "request": request})

        def query(conditions, ids=None):
            body = {
                "object_type": "SourceJournalMovement",
                "filters": conditions,
                "valid_at": request["valid_at"],
                "known_at": request["known_at"],
                "limit": 200,
            }
            if ids is not None:
                body["resource_ids"] = ids
            response = client.post("/object-sets/query", json=body)
            response.raise_for_status()
            return response.json()

        window = query(filters())
        lower = query(
            [
                {"field": "source_family", "value": FAMILY},
                {"field": "posting_date", "value": LOWER},
            ]
        )
        upper = query(
            [
                {"field": "source_family", "value": FAMILY},
                {"field": "posting_date", "value": UPPER},
            ]
        )
        assert lower["total"] > 0 and upper["total"] > 0
        assert window["next_offset"] is None and window["total"] == lower["total"]
        assert all(
            LOWER <= obj["attributes"]["posting_date"] < UPPER
            for obj in window["objects"]
        )
        ids = {obj["resource_id"] for obj in window["objects"]}
        assert ids == {obj["resource_id"] for obj in lower["objects"]}
        assert ids.isdisjoint({obj["resource_id"] for obj in upper["objects"]})
        assert all(
            obj["evidence_class"] == "SOURCE_BOUND"
            and obj["attributes"]["evidence_id"] == EVIDENCE
            for obj in window["objects"]
        )
        readback = query([], sorted(ids))
        assert readback["objects"] == window["objects"]
        if not args.read_only:
            response = client.post("/functions/invocations", json=request)
            response.raise_for_status()
        response = client.get(f"/functions/invocations/{request['request_id']}")
        response.raise_for_status()
        invocation = response.json()
        assert invocation["status"] == "SUCCEEDED"
        assert invocation["output"]["objects"] == window["objects"]
        assert invocation["output"]["derived_values"] == []
        assert invocation["output"]["current_use_authorized"] is False
        assert invocation["output"]["business_effect_authorized"] is False
        if previous and previous.get("invocation"):
            assert invocation == previous["invocation"]
        evidence_pins = {}
        evidence_bindings = []
        for obj in window["objects"]:
            response = client.get(
                f"/operator/trace/{obj['resource_id']}",
                params={
                    "version_id": obj["version_id"],
                    "known_at": request["known_at"],
                },
            )
            response.raise_for_status()
            trace = response.json()
            edges = [
                edge
                for edge in trace["edges"]
                if edge["source_version_id"] == obj["version_id"]
                and edge["relation"] == "FIELD:evidence_id"
            ]
            assert len(edges) == 1
            evidence_version = edges[0]["target_version_id"]
            target = next(
                node
                for node in trace["nodes"]
                if node["version_id"] == evidence_version
            )
            assert target["resource_id"] == EVIDENCE
            response = client.get(
                f"/operator/resources/{EVIDENCE}",
                params={
                    "version_id": evidence_version,
                    "known_at": request["known_at"],
                },
            )
            response.raise_for_status()
            evidence = response.json()["resource"]
            assert evidence["version_id"] == evidence_version
            assert evidence["object_type"] == "SourceEvidence"
            assert evidence["resource_id"] == target["resource_id"]
            assert evidence["attributes"]["sha256"] == SOURCE_HASH
            evidence_pins[evidence_version] = {
                key: evidence[key]
                for key in ("resource_id", "version_id", "content_hash")
            }
            evidence_bindings.append(
                {
                    "object_resource_id": obj["resource_id"],
                    "object_version_id": obj["version_id"],
                    "evidence_version_id": evidence_version,
                }
            )
        assert evidence_pins
    save(
        args.output,
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "request": request,
            "window": window,
            "lower_boundary": lower,
            "excluded_upper_boundary": upper,
            "invocation": invocation,
            "source_sha256": SOURCE_HASH,
            "source_evidence_pins": list(evidence_pins.values()),
            "source_evidence_bindings": evidence_bindings,
            "exact_object_readback_equal": True,
            "financial_authority_established": False,
            "read_only_verification": args.read_only,
        },
    )
    print(
        "Authentic posting-date window and exact retained Function output verified; no financial aggregation."
    )


if __name__ == "__main__":
    main()

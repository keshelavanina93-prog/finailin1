"""Prove exact-version text-property composition over one retained source account."""

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
    "composition_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(loader)
loader.loader.exec_module(shared)
KEY = "source-account:exact-derived-composition:v1"
SCHEMA = "e365d1cd-40f1-5fa5-8343-3db93f32e4aa"
ACCOUNT = "00c93da8-3ab9-5597-aaf6-ea79b7307d32"


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def base(author, reviewer, corrected=False):
    expression = {"op": "field", "field": "account_code"}
    if corrected:
        expression = {
            "op": "concat",
            "args": [expression, {"op": "literal", "value": ":"}],
        }
    return shared.publish(
        author,
        reviewer,
        "DerivedProperty",
        KEY + ":base",
        "Observed account code" + (" with reviewed colon suffix" if corrected else ""),
        {
            "schema_id": SCHEMA,
            "definition": {
                "name": "observed_account_code",
                "result_kind": "text",
                "expression": expression,
            },
        },
    )


def prepare(author, reviewer):
    original = base(author, reviewer)
    composed = shared.publish(
        author,
        reviewer,
        "DerivedProperty",
        KEY + ":composed",
        "Source account code and observed name",
        {
            "schema_id": SCHEMA,
            "definition": {
                "name": "observed_account_label",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [
                        {"op": "derived", "property": pin(original)},
                        {"op": "literal", "value": " | "},
                        {"op": "field", "field": "source_name"},
                    ],
                },
            },
        },
    )
    query = {"object_type": "SourceAccountDefinition", "resource_ids": [ACCOUNT]}
    selected = shared.publish(
        author,
        reviewer,
        "ObjectSetDefinition",
        KEY,
        "One retained source account for property composition",
        {"definition": query},
    )
    manifest = function_execution.manifest()
    function = shared.publish(
        author,
        reviewer,
        "FunctionDefinition",
        KEY,
        "Compose observed account code and source name",
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
                "derived_property_ids": [composed["resource_id"]],
            },
        },
    )
    return {
        "base": pin(original),
        "composed": pin(composed),
        "object_set": pin(selected),
        "function": pin(function),
        "query": query,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    for name in ("prepare", "correct", "replay", "read-only"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin6-derived-composition-runtime.json"),
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
        assert previous.get("invocation"), (
            "Execute the original composition before correction"
        )
        assert not previous.get("correction"), "Correction already retained; use replay"
        previous["correction"] = pin(base(author, reviewer, True))
        save(args.output, previous)
    request = previous.get("request")
    if request is None:
        assert not (args.replay or args.read_only)
        now = datetime.now(UTC).isoformat()
        request = {
            "request_id": str(uuid4()),
            "function": prepared["function"],
            "valid_at": now,
            "known_at": now,
            "offset": 0,
            "limit": 1,
        }
        previous["request"] = request
        save(args.output, previous)
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": "Bearer " + token}, timeout=90
    ) as client:

        def derive(reference):
            response = client.post(
                "/model/derived/query",
                json={
                    "query": {
                        **prepared["query"],
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
            result = response.json()
            reopened = client.get("/model/fact-runs/" + result["run_id"])
            reopened.raise_for_status()
            assert reopened.json() == result
            return result

        if args.read_only:
            calculation = client.get(
                "/model/fact-runs/" + previous["calculation"]["run_id"]
            )
            calculation.raise_for_status()
            calculation = calculation.json()
            assert calculation == previous["calculation"]
        else:
            calculation = derive(prepared["composed"])
        if previous.get("calculation"):
            assert calculation == previous["calculation"]
        assert len(calculation["objects"]) == 1
        obj = calculation["objects"][0]
        assert obj["resource_id"] == ACCOUNT and obj["evidence_class"] == "SOURCE_BOUND"
        expected = (
            obj["attributes"]["account_code"] + " | " + obj["attributes"]["source_name"]
        )
        values = calculation["derived_values"]
        assert len(values) == 1 and values[0]["status"] == "AVAILABLE"
        assert values[0]["value"] == expected
        assert values[0]["definition_version_id"] == prepared["composed"]["version_id"]
        assert calculation["derived_graph"]
        dependencies = values[0]["dependency_values"]
        assert len(dependencies) == 1
        dependency = dependencies[0]
        assert dependency["definition_id"] == prepared["base"]["resource_id"]
        assert dependency["definition_version_id"] == prepared["base"]["version_id"]
        assert dependency["value"] == obj["attributes"]["account_code"]
        assert dependency["status"] == "AVAILABLE"
        assert dependency["source_fields"][0]["field"] == "account_code"
        assert (
            dependency["source_fields"][0]["object_content_hash"] == obj["content_hash"]
        )
        assert values[0]["source_fields"][0]["field"] == "source_name"
        assert (
            values[0]["source_fields"][0]["value"] == obj["attributes"]["source_name"]
        )
        if not args.read_only:
            response = client.post("/functions/invocations", json=request)
            response.raise_for_status()
        response = client.get("/functions/invocations/" + request["request_id"])
        response.raise_for_status()
        invocation = response.json()
        assert invocation["status"] == "SUCCEEDED"
        assert invocation["output"]["objects"] == calculation["objects"]
        assert invocation["output"]["derived_values"] == values
        assert invocation["output"]["derived_graph"] == calculation["derived_graph"]
        assert invocation["output"]["business_effect_authorized"] is False
        if previous.get("invocation"):
            assert invocation == previous["invocation"]
        corrected = previous.get("corrected_calculation")
        if previous.get("correction") and not args.read_only:
            corrected = derive(previous["correction"])
            assert (
                corrected["derived_values"][0]["value"]
                == obj["attributes"]["account_code"] + ":"
            )
            assert (
                corrected["derived_values"][0]["definition_version_id"]
                != prepared["base"]["version_id"]
            )
    save(
        args.output,
        {
            **previous,
            "phase": "CORRECTION_REPLAY_VERIFIED"
            if previous.get("correction")
            else "RUNTIME_VERIFIED",
            "checked_at": datetime.now(UTC).isoformat(),
            "calculation": calculation,
            "invocation": invocation,
            "corrected_calculation": corrected,
            "financial_authority_established": False,
            "read_only_verification": args.read_only,
            "replayed_existing_receipts": bool(previous.get("invocation")),
        },
    )
    print("Exact derived composition and retained calculation/Function proof verified.")


if __name__ == "__main__":
    main()

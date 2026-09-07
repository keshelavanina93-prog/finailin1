"""Verify source-scoped membership queries through shared SDK and retained Functions."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from finai_api.domain.review import Principal
from finai_api.services import function_execution

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "membership_shared", ROOT / "scripts/verify-transformation-input-runtime.py"
)
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
KEY = "sog-source-contexts:membership:v1"
EVIDENCE = "71f45f39-35fb-56c1-b4b7-61e7edc56368"
EXPECTED = {
    "7959af7f-a1bb-5573-8006-d1fc14f58681",
    "2bd64825-e320-5039-b163-2064a1a71c82",
}


def query(operator="in", values=None):
    return {
        "object_type": "CompanyDimension",
        "filters": [
            {"field": "evidence_id", "value": EVIDENCE},
            {
                "field": "source_column",
                "operator": operator,
                "value": values if values is not None else ["Y", "AA"],
            },
        ],
    }


def pin(row):
    return {key: row[key] for key in ("resource_id", "version_id")}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


NODE_PROOF = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const {createOntologyClient} = await import(input.sdk);
const selected = Object.entries(JSON.parse(process.env.FINAI_ACCESS_TOKENS)).find(([,g]) =>
 ['ontology_admin','ontology_propose','ontology_read'].every(p => g.permissions.includes(p)));
assert.ok(selected);
const client = createOntologyClient({baseUrl:input.base_url,getToken:()=>selected[0]});
const options = {...input.time,limit:1,offset:0};
const first = await client.runSavedSet(input.object_set, options);
const second = await client.nextPage(first);
assert.ok(second);
assert.equal(first.total,2); assert.equal(second.total,2);
assert.equal(await client.nextPage(second),null);
assert.deepEqual(await client.page(second,0),first);
assert.deepEqual(first.query.filters,input.query.filters);
assert.deepEqual(second.query.filters,first.query.filters);
assert.equal(second.query.valid_at,first.query.valid_at);
assert.equal(second.query.known_at,first.query.known_at);
const utc = x => x.replace(/(?:Z|\+00:00)$/,'Z').replace(/\.(\d*?)0+Z$/,(_,f)=>f?'.'+f+'Z':'Z');
assert.equal(utc(first.query.valid_at),utc(input.time.valid_at));
assert.equal(utc(first.query.known_at),utc(input.time.known_at));
const result = await client.query({...input.query,...input.time,limit:10});
assert.deepEqual([...first.objects,...second.objects],result.objects);
const excluded = await client.query({...input.excluded,...input.time,limit:10});
assert.deepEqual(excluded.objects,result.objects);
const traversal = await client.query({...input.query,...input.time,limit:10,
 traversal:[{kind:'reference',name:'source_record_id',direction:'outgoing',
 filters:[{field:'evidence_id',operator:'in',value:[input.evidence]}]}]});
assert.deepEqual(new Set(traversal.objects.map(o=>o.resource_id)),new Set(result.objects.map(o=>o.attributes.source_record_id)));
process.stdout.write(JSON.stringify({result,excluded,traversal,pages:[first,second]}));
"""


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
        default=Path("docs/development/evidence/nin6-membership-query-runtime.json"),
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
        selected = shared.publish(
            author,
            reviewer,
            "ObjectSetDefinition",
            KEY,
            "Region and Department source columns",
            {"definition": query()},
        )
        manifest = function_execution.manifest()
        function = shared.publish(
            author,
            reviewer,
            "FunctionDefinition",
            KEY,
            "Read source columns selected by membership",
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
        prepared = {
            "object_set": pin(selected),
            "function": pin(function),
            "query": query(),
        }
        save(args.output, {"phase": "DEFINITIONS_PREPARED", "prepared": prepared})
        print(json.dumps(prepared))
        return
    previous = json.loads(args.output.read_text(encoding="utf-8"))
    prepared = previous["prepared"]
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
            "limit": 10,
        }
        previous["request"] = request
        save(args.output, previous)
    executable = shutil.which("node")
    assert executable and Path(executable).resolve().drive.lower() == "d:"
    sdk = subprocess.run(
        [str(Path(executable).resolve()), "--input-type=module", "--eval", NODE_PROOF],
        cwd=ROOT,
        input=json.dumps(
            {
                "sdk": (ROOT / "packages/ontology-client/dist/index.js").as_uri(),
                "base_url": args.base_url,
                "object_set": prepared["object_set"],
                "query": prepared["query"],
                "excluded": query("not_in", ["Z"]),
                "evidence": EVIDENCE,
                "time": {key: request[key] for key in ("valid_at", "known_at")},
            }
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    result = json.loads(sdk.stdout)
    assert {obj["resource_id"] for obj in result["result"]["objects"]} == EXPECTED
    assert {
        obj["attributes"]["source_column"] for obj in result["result"]["objects"]
    } == {"Y", "AA"}
    assert all(
        obj["attributes"]["evidence_id"] == EVIDENCE
        for obj in result["result"]["objects"]
    )
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + token},
        timeout=90,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        if not args.read_only:
            response = client.post("/functions/invocations", json=request)
            response.raise_for_status()
        response = client.get("/functions/invocations/" + request["request_id"])
        response.raise_for_status()
        invocation = response.json()
        assert invocation["status"] == "SUCCEEDED"
        assert invocation["output"]["objects"] == result["result"]["objects"]
        assert invocation["output"]["query"]["filters"] == prepared["query"]["filters"]
        assert invocation["output"]["current_use_authorized"] is False
        assert invocation["output"]["business_effect_authorized"] is False
        if previous.get("invocation"):
            assert invocation == previous["invocation"]
            assert result == previous["sdk"]
    save(
        args.output,
        {
            **previous,
            "phase": "MEMBERSHIP_SDK_FUNCTION_VERIFIED",
            "sdk": result,
            "invocation": invocation,
            "checked_at": datetime.now(UTC).isoformat(),
            "financial_authority_established": False,
            "read_only_verification": args.read_only,
        },
    )
    print("Source-scoped membership, SDK exact paging and retained Function verified.")


if __name__ == "__main__":
    main()

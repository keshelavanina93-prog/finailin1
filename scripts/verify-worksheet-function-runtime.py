"""Review and execute retained SGP worksheet pages through the shared build runtime.

No upload, workbook interpretation or accounting authority is established. Run after
the settled package and schema have been installed. All proof files stay on D:.
"""

import argparse
import json
import os
from datetime import UTC, datetime

# Reuse the shared retained-build verification helpers, without submitting their job.
from importlib.util import module_from_spec, spec_from_file_location
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
from finai_api.services.source_documents import list_documents
from finai_api.services.workspace import WorkspaceError

_spec = spec_from_file_location(
    "retained_build_proof", Path(__file__).with_name("verify-transformation-runtime.py")
)
assert _spec and _spec.loader
_helpers = module_from_spec(_spec)
_spec.loader.exec_module(_helpers)

SHA = "74e6f0d96943c48280854d8e437a9a78565c7796656ba07efe640ce398e381f8"
FUNCTION_KEY = "source-sgp:reviewed-title-worksheet:v1"
BUILD_KEY = "source-sgp:reviewed-title-build:v1"
IMPLEMENTATION = "source.retained-xls-worksheet/v1"


def publish(
    p: Principal, reviewer: Principal, kind: str, key: str, label: str, attrs: dict
) -> dict:
    identity = canonical_id(p.scope.tenant_id, kind, key)
    try:
        previous = resources.get_resource(p, identity)["resource"]
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
        previous = None
    # Re-review also refreshes exact dependencies after a package revision.
    proposal = ResourceProposal(
        title=label,
        rationale="Pin retained worksheet evidence and bounded source-only execution; no financial activation",
        access_entity=p.scope.legal_entity_id,
        mutations=[
            ResourceMutation(
                resource_id=identity,
                object_type=kind,
                identity_key=key,
                display_name=label,
                expected_version_id=UUID(str(previous["version_id"]))
                if previous
                else None,
                valid_from=datetime.now(UTC),
                attributes=attrs,
            )
        ],
    )
    resources.propose(p, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independently reviewed immutable source pin, worksheet window and execution-only outputs",
        ),
    )
    result = resources.get_resource(p, identity)["resource"]
    return {
        "resource_id": str(identity),
        "version_id": str(result["version_id"]),
        "proposal_id": str(proposal.proposal_id),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--replay", action="store_true")
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin32-worksheet-runtime.json"),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    required = (
        {"ontology_admin", "ontology_propose", "ontology_read"}
        if args.prepare
        else {"ingest", "ontology_read"}
    )
    token, p = next(
        (t, Principal.model_validate(g))
        for t, g in grants.items()
        if required.issubset(g["permissions"])
    )
    build_id = canonical_id(p.scope.tenant_id, "TransformationDefinition", BUILD_KEY)
    if args.prepare:
        reviewer = next(
            Principal.model_validate(g)
            for g in grants.values()
            if {"ontology_admin", "ontology_review"}.issubset(g["permissions"])
            and g["actor_id"] != p.actor_id
            and str(g["scope"]["tenant_id"]) == str(p.scope.tenant_id)
        )
        documents = [d for d in list_documents(p) if d["sha256"] == SHA]
        assert len(documents) == 1, "Expected one exact retained SGP source"
        evidence_id = canonical_id(p.scope.tenant_id, "SourceEvidence", SHA)
        resources.get_resource(p, evidence_id)
        manifest = function_execution.manifest(IMPLEMENTATION)
        definition = {
            k: manifest[k]
            for k in (
                "implementation_id",
                "determinism",
                "code_sha256",
                "dependency_sha256",
            )
        }
        definition.update(
            document_id=documents[0]["document_id"],
            source_sha256=SHA,
            sheet="TDSheet",
            first_row=0,
            row_count=6,
        )
        function = publish(
            p,
            reviewer,
            "FunctionDefinition",
            FUNCTION_KEY,
            "SGP source worksheet title",
            {"evidence_id": str(evidence_id), "definition": definition},
        )
        build = publish(
            p,
            reviewer,
            "TransformationDefinition",
            BUILD_KEY,
            "SGP source worksheet build",
            {
                "resource_budget": {
                    "max_returned_rows": 6,
                    "max_derived_evaluations": 0,
                    "max_published_result_bytes": 1000000,
                },
                "definition": {
                    "nodes": [
                        {
                            "node_id": "source_title",
                            "function_id": function["resource_id"],
                            "offset": 0,
                            "limit": 3,
                        },
                        {
                            "node_id": "source_context",
                            "function_id": function["resource_id"],
                            "offset": 3,
                            "limit": 3,
                            "depends_on": ["source_title"],
                        },
                    ],
                    "outputs": [
                        {"output_id": "worksheet_title", "node_id": "source_title"},
                        {"output_id": "worksheet_context", "node_id": "source_context"},
                    ],
                },
            },
        )
        args.output.with_suffix(".preparation.json").write_text(
            json.dumps(
                {"function": function, "build": build, "source_sha256": SHA}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            "Reviewed source worksheet Function and build against the retained SGP evidence."
        )
        return
    previous = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.replay or args.read_only
        else None
    )
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology",
        headers={"Authorization": "Bearer " + token},
        timeout=60,
    ) as client:
        if previous:
            request = previous["request"]
        else:
            response = client.get(f"/resources/{build_id}")
            response.raise_for_status()
            now = datetime.now(UTC).isoformat()
            request = {
                "request_id": str(uuid4()),
                "transformation": {
                    "resource_id": str(build_id),
                    "version_id": response.json()["resource"]["version_id"],
                },
                "valid_at": now,
                "known_at": now,
            }
            args.output.write_text(
                json.dumps({"request": request}, indent=2) + "\n", encoding="utf-8"
            )
        if not args.read_only:
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
        result = _helpers.read_complete(client, request["request_id"], 120)
        assert result["business_effect_authorized"] is False
        assert len(result["publications"]) == 1
        publication = result["publications"][0]
        assert publication["authority"] == "EXECUTION_ONLY"
        assert {o["slot"] for o in publication["outputs"]} == {
            "worksheet_title",
            "worksheet_context",
        }
        outputs = []
        rows = set()
        for output in publication["outputs"]:
            reference = output["value"]
            response = client.get(
                f"/functions/invocations/{reference['invocation_id']}"
            )
            response.raise_for_status()
            invocation = response.json()
            assert invocation["status"] == "SUCCEEDED"
            assert invocation["receipt_hash"] == reference["receipt_hash"]
            payload = invocation["output"]
            assert payload["implementation"]["implementation_id"] == IMPLEMENTATION
            assert payload["objects"] == [] and payload["derived_values"] == []
            assert len(payload["source_rows"]) == 3
            source = payload["source_document"]
            original = client.get(
                f"/source-documents/{source['document_id']}/preview",
                params={
                    "sheet": source["sheet"],
                    "offset": payload["source_query"]["offset"],
                },
            )
            original.raise_for_status()
            assert original.json()["sha256"] == SHA
            assert original.json()["rows"][:3] == payload["source_rows"]
            for row in payload["source_rows"]:
                rows.add(row["row"])
                assert all(
                    cell["coordinate"].startswith("TDSheet!") for cell in row["cells"]
                )
            outputs.append({"output_id": output["slot"], "invocation": invocation})
        assert rows == {1, 2, 3, 4, 5, 6}
        events = {e["event_id"]: e for e in result["events"]}
        usage = [
            events[f"node:{node}:terminal"]["usage"]
            for node in ("source_title", "source_context")
        ]
        assert sum(u["returned_rows"] for u in usage) == 6
        assert sum(u["derived_evaluations"] for u in usage) == 0
        if not args.read_only:
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
        again = _helpers.read_complete(client, request["request_id"], 120)
        assert _helpers.retained_part(again) == _helpers.retained_part(result)
        if previous and previous.get("result"):
            assert _helpers.retained_part(previous["result"]) == _helpers.retained_part(
                result
            )
    args.output.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "request": request,
                "result": result,
                "named_outputs": outputs,
                "source_sha256": SHA,
                "retained_repeat_and_history_equal": True,
                "original_preview_cells_equal": True,
                "financial_authority_established": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Retained SGP build published two source-only outputs; six source rows measured, replay/history identical."
    )


if __name__ == "__main__":
    main()

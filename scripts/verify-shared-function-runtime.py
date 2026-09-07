"""Review and invoke source-account analysis through the shared Function contract."""

import argparse
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

OBJECT_SET = "bbbe95f6-a0d0-4313-ab3e-6ebc73177087"
DERIVED_PROPERTY = "b9fbde64-2cc8-4c4e-bf44-fe8fbb38c13a"
KEY = "source-accounts:reviewed-label-analysis:v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin47-shared-function-runtime.json"),
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
    identity = canonical_id(author.scope.tenant_id, "FunctionDefinition", KEY)
    if args.prepare:
        executable = function_execution.manifest()
        attributes = {
            "object_set_id": OBJECT_SET,
            "definition": {
                **{
                    name: executable[name]
                    for name in (
                        "implementation_id",
                        "determinism",
                        "code_sha256",
                        "dependency_sha256",
                    )
                },
                "derived_property_ids": [DERIVED_PROPERTY],
            },
        }
        previous = None
        try:
            previous = resources.get_resource(author, identity)["resource"]
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
        if previous and previous["attributes"] == attributes:
            print("Reviewed source analysis already matches installed implementation.")
            return
        reviewer = next(
            p
            for value in grants.values()
            if (p := Principal.model_validate(value)).actor_id != author.actor_id
            and p.scope.tenant_id == author.scope.tenant_id
            and {"ontology_admin", "ontology_review"}.issubset(p.permissions)
        )
        proposal = ResourceProposal(
            title="Source account label analysis",
            rationale="Execute the retained source-account query and derived labels as reviewed evidence analysis only",
            access_entity=author.scope.legal_entity_id,
            mutations=[
                ResourceMutation(
                    resource_id=identity,
                    object_type="FunctionDefinition",
                    identity_key=KEY,
                    display_name="Source account labels",
                    expected_version_id=UUID(str(previous["version_id"]))
                    if previous
                    else None,
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
                rationale="Reviewed exact source-query/property and installed code pins; no accounting activation",
            ),
        )
        print(
            "Canonical source analysis reviewed; no ledger or financial authority established."
        )
        return
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology",
        headers={"Authorization": "Bearer " + token},
        timeout=60,
    ) as client:
        if args.replay:
            request = json.loads(args.output.read_text(encoding="utf-8"))["request"]
        else:
            response = client.get(f"/resources/{identity}")
            response.raise_for_status()
            resource = response.json()["resource"]
            cutoff = datetime.now(UTC).isoformat()
            request = {
                "request_id": str(uuid4()),
                "function": {
                    "resource_id": str(identity),
                    "version_id": resource["version_id"],
                },
                "valid_at": cutoff,
                "known_at": cutoff,
                "offset": 0,
                "limit": 5,
            }
        response = client.post("/functions/invocations", json=request)
        response.raise_for_status()
        result = response.json()
        assert result["status"] == "SUCCEEDED", result["status"]
        assert result["current_use_authorized"] is False
        assert result["business_effect_authorized"] is False
        assert len(result["output"]["objects"]) == 5
        assert len(result["output"]["derived_values"]) == 5
        assert all(
            value["status"] == "AVAILABLE"
            for value in result["output"]["derived_values"]
        )
        assert result["output"]["coverage"] == "QUERY_PAGE_ONLY"
        assert result["output"]["mode"] == "EVIDENCE_ANALYSIS_ONLY"
        repeated = client.post("/functions/invocations", json=request)
        repeated.raise_for_status()
        assert repeated.json() == result
        historical = client.get(f"/functions/invocations/{request['request_id']}")
        historical.raise_for_status()
        assert historical.json() == result
    args.output.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "request": request,
                "result": result,
                "repeat_and_history_equal": True,
                "replayed_existing_intent": args.replay,
                "financial_authority_established": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Actual source analysis executed with five retained derived values; repeat/history identical."
    )


if __name__ == "__main__":
    main()

"""Review a technical conformance policy and retain evidence over a real saved Object Set.

This does not certify source authenticity, accounting accuracy or business-use authority.
Run --prepare after installing the canonical CertificationContract schema, then run
without that flag after API/web restart to prove the deployed evaluation/readback path.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

SUBJECT = UUID("bbbe95f6-a0d0-4313-ab3e-6ebc73177087")
POLICY_KEY = "definition-conformance:object-set:structural-v1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token, author = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if {"ontology_admin", "ontology_propose", "ontology_read"}.issubset(
            grant["permissions"]
        )
    )
    policy_id = canonical_id(
        author.scope.tenant_id, "CertificationContract", POLICY_KEY
    )
    if args.prepare:
        try:
            resources.get_resource(author, policy_id)
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            reviewer = next(
                p
                for grant in grants.values()
                if (p := Principal.model_validate(grant)).actor_id != author.actor_id
                and p.scope.tenant_id == author.scope.tenant_id
                and {"ontology_admin", "ontology_review"}.issubset(p.permissions)
            )
            proposal = ResourceProposal(
                title="Saved Object Set definition conformance policy",
                rationale="Retain narrow structural conformance evidence without financial certification",
                access_entity="__PLATFORM__",
                mutations=[
                    ResourceMutation(
                        resource_id=policy_id,
                        object_type="CertificationContract",
                        identity_key=POLICY_KEY,
                        display_name="Saved Object Set structural conformance",
                        valid_from=datetime.now(UTC),
                        attributes={
                            "subject_schema_id": str(
                                canonical_id(
                                    author.scope.tenant_id,
                                    "SchemaDefinition",
                                    "ObjectSetDefinition",
                                )
                            ),
                            "definition": {
                                "claim": "CANONICAL_DEFINITION_CONFORMANCE",
                                "evaluator": "canonical-structural-contract/v1",
                                "subject_type": "ObjectSetDefinition",
                                "required_checks": [
                                    "schema compatibility",
                                    "identity cycles",
                                    "dependency version pins",
                                    "impact",
                                ],
                                "meaning": "The exact saved query definition passed retained structural review checks.",
                                "limitations": "Does not establish source authenticity, accounting accuracy, financial certification or business-use authority.",
                            },
                        },
                    )
                ],
            )
            resources.propose(author, proposal)
            resources.review(
                reviewer,
                proposal.proposal_id,
                ResourceReview(
                    decision="APPROVED",
                    rationale="Reviewed technical claim scope; no financial or source-authenticity claim",
                ),
            )
        print(
            "Canonical technical conformance policy retained through reviewed publication."
        )
        return
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology",
        headers={"Authorization": "Bearer " + token},
        timeout=30,
    ) as client:
        subject_response = client.get(f"/resources/{SUBJECT}")
        subject_response.raise_for_status()
        subject = subject_response.json()["resource"]
        policy_response = client.get(f"/resources/{policy_id}")
        policy_response.raise_for_status()
        policy = policy_response.json()["resource"]
        request_id = str(uuid5(SUBJECT, subject["version_id"] + policy["version_id"]))
        request = {
            "request_id": request_id,
            "subject": {
                "resource_id": str(SUBJECT),
                "version_id": subject["version_id"],
            },
            "contract": {
                "resource_id": str(policy_id),
                "version_id": policy["version_id"],
            },
        }
        response = client.post("/certifications/evaluations", json=request)
        response.raise_for_status()
        receipt = response.json()
        repeated = client.post("/certifications/evaluations", json=request)
        repeated.raise_for_status()
        assert repeated.json() == receipt
        reopened = client.get(f"/certifications/receipts/{receipt['receipt_id']}")
        reopened.raise_for_status()
        retained = reopened.json()
        assert retained["proof"] == receipt["proof"]
        assert retained["proof_hash"] == receipt["proof_hash"]
        assert receipt["current_use_authorized"] is False
        assert retained["current_use_authorized"] is False
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "evaluation_http_status": response.status_code,
        "readback_http_status": reopened.status_code,
        "request": request,
        "receipt": receipt,
        "idempotent_repeat_equal": True,
        "retained_readback_equal": True,
        "scope": "Structural conformance of an actual saved source-account Object Set definition",
        "financial_certification": False,
        "current_use_authorized": False,
        "browser_or_release_acceptance": False,
    }
    if args.output:
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        "Deployed definition conformance evaluation, repeat and historical readback passed."
    )


if __name__ == "__main__":
    main()

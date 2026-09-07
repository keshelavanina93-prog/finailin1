"""Prepare the isolated movement-review Function after canonical code integration.

Read-only by default. --apply uses ordinary separate-actor resource review and
one idempotent Function invocation. Does not promote journals or change bindings.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid5

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import function_execution, function_invocations, resources
from finai_api.services.workspace import WorkspaceError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    grants = [
        Principal.model_validate(v)
        for v in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    ]
    author = next(
        p
        for p in grants
        if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
    )
    reviewer = next(
        p
        for p in grants
        if p.actor_id != author.actor_id
        and p.scope == author.scope
        and {"ontology_admin", "ontology_review"} <= set(p.permissions)
    )
    operator = next(
        p
        for p in grants
        if p.scope == author.scope
        and "ingest" in p.permissions
        and "ontology_admin" not in p.permissions
    )
    binding_id = UUID("f4cf95a5-9552-519c-8e59-96ee06bd4308")
    identity = uuid5(binding_id, "entity-source-movement-review/function-v1")
    manifest = function_execution.manifest("accounting.retained-posted-movements/v1")
    definition = {
        key: manifest[key]
        for key in (
            "implementation_id",
            "determinism",
            "code_sha256",
            "dependency_sha256",
        )
    }
    definition.update(
        document_id="ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6",
        source_sha256="d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a",
        sheet="Base",
        max_source_rows=1000,
        entity_movement_review=True,
    )
    attrs = {
        "definition": definition,
        "accounting_binding_id": str(binding_id),
        "source_scope_id": "23558068-046d-5fed-8582-3211ea2f2199",
        "evidence_id": "f2a292a5-7f7c-533e-8caf-dd0a32b16fa4",
        "minimum_authority_state": "OBSERVED",
    }
    result = {
        "mode": "APPLIED" if args.apply else "READ_ONLY_PREPARATION",
        "function_id": str(identity),
        "definition": attrs,
        "canonical_journal_promotion": False,
    }
    if args.apply:
        prior = resources.current_resources(author, [identity]).get(str(identity))
        if prior is None or prior["attributes"] != attrs:
            reason = "Review exact SEG source-pair reconciliation and movement-only account view. Journal profile, precision and dimension gates stay enforced; no accepted journal or complete trial-balance claim."
            proposal = ResourceProposal(
                title="Review SEG source movement reconciliation",
                rationale=reason,
                access_entity=author.scope.legal_entity_id,
                mutations=[
                    ResourceMutation(
                        resource_id=identity,
                        expected_version_id=prior["version_id"] if prior else None,
                        object_type="FunctionDefinition",
                        identity_key="seg-entity-source-movement-review",
                        display_name="SEG January 2025 reconciled source movements",
                        attributes=attrs,
                        valid_from=datetime.now(UTC),
                        evidence_class="USER_ASSERTED",
                    )
                ],
            )
            resources.propose(author, proposal)
            resources.review(
                reviewer,
                proposal.proposal_id,
                ResourceReview(decision="APPROVED", rationale=reason),
            )
        function = resources.get_resource(operator, identity)["resource"]
        at = datetime.fromisoformat(str(function["system_from"]))
        request = FunctionInvocation(
            request_id=uuid5(UUID(str(function["version_id"])), operator.actor_id),
            function={"resource_id": identity, "version_id": function["version_id"]},
            valid_at=at,
            known_at=at,
            limit=100,
        )
        try:
            history = function_invocations.history(operator, request.request_id)
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            history = function_invocations.invoke(operator, request)
        if history["status"] == "INTENT_RETAINED":
            history = function_invocations.invoke(operator, request)
        assert history["status"] == "SUCCEEDED", history["receipt"].get("failure_code")
        result["invocation"] = {
            "invocation_id": history["invocation_id"],
            "receipt_hash": history["receipt_hash"],
            "run_id": history["output"]["run_id"],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

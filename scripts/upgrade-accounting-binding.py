"""Publish additive accounting interpretation schemas through shared review, preserving history."""

import json
import os
from datetime import UTC, datetime

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resources


def main():
    principals = [
        Principal.model_validate(value)
        for value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    ]
    author = next(
        p
        for p in principals
        if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
    )
    reviewer = next(
        p
        for p in principals
        if p.actor_id != author.actor_id
        and p.scope.tenant_id == author.scope.tenant_id
        and {"ontology_admin", "ontology_review"} <= set(p.permissions)
    )
    mutations = []
    for spec in platform_definitions(author.scope.tenant_id):
        if spec["object_type"] != "SchemaDefinition" or spec["identity_key"] not in {
            "SourceAccountingBinding",
            "JournalEntry",
            "JournalLine",
        }:
            continue
        identity = canonical_id(
            author.scope.tenant_id, "SchemaDefinition", spec["identity_key"]
        )
        prior = resources.get_resource(author, identity)["resource"]
        if prior["attributes"] == spec["attributes"]:
            continue
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                expected_version_id=prior["version_id"],
                valid_from=datetime.now(UTC),
                **spec,
            )
        )
    if not mutations:
        print(json.dumps({"status": "ALREADY_CURRENT"}))
        return
    proposal = ResourceProposal(
        title="Version source accounting interpretation and journal binding contracts",
        rationale="Add explicit currency roles, mapping pins, source granularity, amount semantics "
        "and unresolved review candidates. Retain all prior schema and resource versions.",
        access_entity="__PLATFORM__",
        mutations=mutations,
    )
    resources.propose(author, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Additive canonical contracts; no enterprise accounting values or identities changed",
        ),
    )
    print(
        json.dumps(
            {
                "status": "REVIEWED_SCHEMA_UPGRADE",
                "proposal_id": str(proposal.proposal_id),
                "schemas": [m.identity_key for m in mutations],
            },
            default=str,
        )
    )


if __name__ == "__main__":
    main()

"""Install missing ontology contracts through the existing independent publication path."""

import json
import os
from datetime import UTC, datetime

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.ontology_definitions import DEFINITION_MODELS
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


def main() -> None:
    principals = [
        Principal.model_validate(p)
        for p in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    ]
    author = next(
        p
        for p in principals
        if {"ontology_admin", "ontology_propose"}.issubset(p.permissions)
    )
    reviewer = next(
        p
        for p in principals
        if p.actor_id != author.actor_id
        and p.scope.tenant_id == author.scope.tenant_id
        and {"ontology_admin", "ontology_review"}.issubset(p.permissions)
    )
    kinds = {
        "FunctionDefinition",
        "RetentionPolicy",
        "CertificationContract",
        "SourceRegulatoryPublication",
        *DEFINITION_MODELS,
        "SourceAccountDefinition",
        "SourceJournalMovement",
        "SourceTrialBalanceRow",
        "CompanyDimension",
        "CompanyWorkspace",
        "SourceDimensionAssignment",
        "SourceAccountingScope",
        "SourceAccountingBinding",
        "SourceCorporateObservation",
        "CorporateDisclosureBinding",
        "SourceLicenceNotice",
        "LicenceNoticeBinding",
    }
    mutations = []
    for spec in platform_definitions(author.scope.tenant_id):
        if not (
            (
                spec["object_type"] == "SchemaDefinition"
                and spec["identity_key"] in kinds
            )
            or (
                spec["object_type"] == "SemanticContract"
                and spec["identity_key"] == "OntologyDefinition"
            )
        ):
            continue
        identity = canonical_id(
            author.scope.tenant_id, spec["object_type"], spec["identity_key"]
        )
        try:
            resources.get_resource(author, identity)
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            mutations.append(
                ResourceMutation(
                    resource_id=identity, valid_from=datetime.now(UTC), **spec
                )
            )
    if not mutations:
        print("Ontology runtime contracts already present; preserved accepted versions")
        return
    proposal = ResourceProposal(
        title="Install executable ontology contracts",
        rationale="Versioned queries, bindings, interfaces, derived properties and accounting aggregation contracts",
        access_entity="__PLATFORM__",
        mutations=mutations,
    )
    resources.propose(author, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independent publication of typed platform contracts without enterprise data",
        ),
    )
    print("Installed ontology contracts", len(mutations), str(proposal.proposal_id))


if __name__ == "__main__":
    main()

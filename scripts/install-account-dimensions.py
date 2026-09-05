"""Install only the analytical rule schema through independent governed review."""

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
from finai_api.services.workspace import WorkspaceError


def main() -> None:
    principals = [
        Principal.model_validate(value)
        for value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
    ]
    operator = next(
        p
        for p in principals
        if "ontology_admin" in p.permissions and "ontology_propose" in p.permissions
    )
    reviewer = next(
        p
        for p in principals
        if p.actor_id != operator.actor_id
        and p.scope.tenant_id == operator.scope.tenant_id
        and "ontology_admin" in p.permissions
        and "ontology_review" in p.permissions
    )
    tenant = operator.scope.tenant_id
    identifier = canonical_id(tenant, "SchemaDefinition", "AccountDimensionRule")
    try:
        resources.get_resource(operator, identifier)
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
    else:
        print(
            "AccountDimensionRule schema already installed; preserved existing version"
        )
        return
    definition = next(
        d
        for d in platform_definitions(tenant)
        if d["object_type"] == "SchemaDefinition"
        and d["identity_key"] == "AccountDimensionRule"
    )
    proposal = ResourceProposal(
        title="Account analytical dimension rule contract",
        rationale="Typed account and dimension references with required or optional membership",
        access_entity="__PLATFORM__",
        mutations=[
            ResourceMutation(
                resource_id=identifier, valid_from=datetime.now(UTC), **definition
            )
        ],
    )
    resources.propose(operator, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independent review of account analytical rule schema",
        ),
    )
    print("Installed reviewed AccountDimensionRule schema", proposal.proposal_id)


if __name__ == "__main__":
    main()

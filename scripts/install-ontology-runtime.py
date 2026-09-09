"""Install platform ontology definitions in dependency phases with independent review.

Company constructions are never installed here. Existing accepted fields retain their
identities and constraints; only compatible missing fields and new definitions are added.
"""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import finance_ontology, resources
from finai_api.services.schema_compatibility import schema_compatibility
from finai_api.services.workspace import WorkspaceError

BATCH_LIMIT = 75
LEGACY_PHASE = "LegacyPlatformContracts"
LEGACY_SCHEMA_KEYS = {
    "Artifact",
    "JournalEntry",
    "JournalLine",
    "PeriodControl",
    "AccountDimensionPolicy",
    "DeploymentTarget",
    "RuntimeAgent",
    "DesiredState",
    "FunctionDefinition",
    "TransformationDefinition",
    "RetentionPolicy",
    "CertificationContract",
    "SourceRegulatoryPublication",
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


def compatible_attributes(
    spec: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any]:
    before = deepcopy(previous["attributes"])
    attributes = deepcopy(before)
    if spec["object_type"] != "SchemaDefinition":
        return attributes
    fields = attributes["fields"]
    for name, definition in spec["attributes"]["fields"].items():
        if name not in fields:
            # Additive installation cannot impose a new requirement on accepted instances.
            fields[name] = {**definition, "required": False}
    if spec["identity_key"] == "FunctionDefinition" and "object_set_id" in fields:
        fields["object_set_id"] = {**fields["object_set_id"], "required": False}
    result = schema_compatibility(spec["identity_key"], attributes, before)
    if result["compatibility"] != "BACKWARD_COMPATIBLE":
        raise ValueError(
            "Ontology installer cannot perform a breaking schema migration"
        )
    return attributes


def install(author: Principal, reviewer: Principal) -> dict[str, Any]:
    if (
        author.actor_id == reviewer.actor_id
        or author.scope.tenant_id != reviewer.scope.tenant_id
    ):
        raise ValueError(
            "Ontology installation requires a distinct reviewer in the same tenant"
        )
    compiled = finance_ontology.compilation(author.scope.tenant_id)
    specs = list(compiled.definitions)
    legacy = platform_definitions(author.scope.tenant_id)
    known = {(spec["object_type"], spec["identity_key"]) for spec in specs}
    for spec in legacy:
        if (
            (
                spec["object_type"] == "SchemaDefinition"
                and spec["identity_key"] in LEGACY_SCHEMA_KEYS
            )
            or (
                spec["object_type"] == "SemanticContract"
                and spec["identity_key"] == "OntologyDefinition"
            )
        ) and (spec["object_type"], spec["identity_key"]) not in known:
            specs.append(spec)
    phases = (*finance_ontology.PHASES, LEGACY_PHASE)
    if any(
        spec["object_type"] not in finance_ontology.PHASES
        and spec["object_type"] not in {"SchemaDefinition", "SemanticContract"}
        for spec in specs
    ):
        raise ValueError("Installation plan contains a non-platform construction")
    published, preserved = [], []
    for phase in phases:
        mutations = []
        for specification in specs:
            in_phase = specification["object_type"] == phase
            if phase == LEGACY_PHASE:
                in_phase = specification["object_type"] not in finance_ontology.PHASES
            if not in_phase:
                continue
            spec = deepcopy(specification)
            identity_kind = (
                spec["object_type"] if phase == LEGACY_PHASE else phase
            )
            identity = canonical_id(
                author.scope.tenant_id, identity_kind, spec["identity_key"]
            )
            expected = None
            try:
                previous = resources.get_resource(author, identity)["resource"]
            except WorkspaceError as exc:
                if exc.status != 404:
                    raise
            else:
                if previous["authority_state"] != "APPROVED":
                    preserved.append(str(identity))
                    continue
                attributes = compatible_attributes(spec, previous)
                if attributes == previous["attributes"]:
                    if spec["attributes"] != attributes:
                        preserved.append(str(identity))
                    continue
                spec.update(
                    attributes=attributes, display_name=previous["display_name"]
                )
                expected = UUID(previous["version_id"])
            mutations.append(
                ResourceMutation(
                    resource_id=identity,
                    expected_version_id=expected,
                    valid_from=datetime.now(UTC),
                    evidence_class="REFERENCE_TEMPLATE",
                    **spec,
                )
            )
        # Finish each dependency phase before publishing resources that refer to it.
        for offset in range(0, len(mutations), BATCH_LIMIT):
            page = mutations[offset : offset + BATCH_LIMIT]
            proposal = ResourceProposal(
                title="Install executable ontology definitions: " + phase,
                rationale="Publish typed platform definitions while preserving accepted versions and company facts",
                access_entity="__PLATFORM__",
                mutations=page,
            )
            resources.propose(author, proposal)
            resources.review(
                reviewer,
                proposal.proposal_id,
                ResourceReview(
                    decision="APPROVED",
                    rationale="Independent review of platform definitions without promotion of company instances",
                ),
            )
            published.append(
                {
                    "phase": phase,
                    "count": len(page),
                    "proposal_id": str(proposal.proposal_id),
                }
            )
    return {
        "published": published,
        "preserved_differences": preserved,
        "company_instances_published": 0,
        "diagnostics": compiled.diagnostics,
    }


def main() -> None:
    principals = [
        Principal.model_validate(value)
        for value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
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
    result = install(author, reviewer)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

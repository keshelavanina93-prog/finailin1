"""Review the typed source-family baseline against the current authentic SEG binding.

Defaults to a read-only inspection. --apply publishes only the two shared schemas
and the reviewed family baseline through separate configured proposal/review actors.
No later source, adoption, ledger posting or calculation is fabricated.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.domain.source_adoption import SourceFamilySelection
from finai_api.services import resources, source_adoption
from finai_api.services.workspace import WorkspaceError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
grants = [
    Principal.model_validate(value)
    for value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
]
maker = next(
    p for p in grants if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
)
checker = next(
    p
    for p in grants
    if p.actor_id != maker.actor_id
    and p.scope.tenant_id == maker.scope.tenant_id
    and {"ontology_admin", "ontology_review"} <= set(p.permissions)
)
reason = (
    "Retain SEG statutory 1C Base source family against its reviewed January 2025 "
    "company, accounting context and original cells. Later snapshots require explicit "
    "compatibility and their own period; no totals or full-ledger completeness are authorized."
)
schemas = []
for spec in platform_definitions(maker.scope.tenant_id):
    if spec["object_type"] != "SchemaDefinition" or spec["identity_key"] not in {
        "SourceFamily",
        "SourceSnapshotAdoption",
    }:
        continue
    identity = canonical_id(
        maker.scope.tenant_id, "SchemaDefinition", spec["identity_key"]
    )
    prior = resources.current_resources(maker, [identity]).get(str(identity))
    if prior and prior["attributes"] == spec["attributes"]:
        continue
    schemas.append(
        ResourceMutation(
            resource_id=identity,
            expected_version_id=prior["version_id"] if prior else None,
            valid_from=datetime.now(UTC),
            **spec,
        )
    )
schema_proposal = None
if schemas and args.apply:
    proposal = ResourceProposal(
        title="Register shared recurring source authority contracts",
        rationale=reason,
        access_entity="__PLATFORM__",
        mutations=schemas,
    )
    resources.propose(maker, proposal)
    resources.review(
        checker,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale=reason),
    )
    schema_proposal = str(proposal.proposal_id)
binding_id = UUID("f4cf95a5-9552-519c-8e59-96ee06bd4308")
binding = resources.get_resource(maker, binding_id)["resource"]
selection = SourceFamilySelection(
    family_key="seg-statutory-base",
    source_system="1C",
    display_name="SEG statutory 1C recorder lines",
    baseline_binding={
        "resource_id": binding["resource_id"],
        "version_id": binding["version_id"],
    },
    rationale=reason,
)
prepared = source_adoption.prepare(maker, selection)
baseline = prepared["attributes"]["definition"]["baseline"]
assert (
    baseline["source_sha256"]
    == "d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a"
)
assert baseline["source_rows"] == 596
assert baseline["missing_amount_count"] == 1
assert baseline["missing_amount_coordinates"] == ["Base!S288"]
assert baseline["coverage_state"] == "UNESTABLISHED"
assert baseline["company"]["resource_id"] == "365aa5d9-c2ec-52e1-867a-50fe3415f486"
proposal_id = None
separate_actor_refusal = None
if args.apply:
    prior = prepared["previous"]
    if not prior or prior["attributes"] != prepared["attributes"]:
        proposed = source_adoption.propose(maker, selection)
        proposal_id = proposed.proposal.proposal_id
        review = ResourceReview(decision="APPROVED", rationale=reason)
        try:
            resources.review(maker, proposal_id, review)
        except WorkspaceError as exc:
            if exc.status != 403 or "separate" not in exc.detail.lower():
                raise
            separate_actor_refusal = exc.detail
        else:
            raise AssertionError("The source-family proposer reviewed its own change")
        resources.review(checker, proposal_id, review)
    prepared = source_adoption.prepare(maker, selection)
    assert prepared["previous"]["authority_state"] == "APPROVED"
    assert prepared["previous"]["attributes"] == prepared["attributes"]
result = {
    "mode": "APPLIED" if args.apply else "READ_ONLY",
    "schema_proposal_id": schema_proposal,
    "family_proposal_id": str(proposal_id) if proposal_id else None,
    "same_actor_refusal": separate_actor_refusal,
    "family": source_adoption.pin(prepared["previous"]).model_dump(mode="json")
    if prepared["previous"]
    else {"resource_id": prepared["resource_id"]},
    "baseline": baseline,
    "exact_dependency_count": len(prepared["source_versions"]),
    "adoption_published": False,
    "authentic_later_source_acceptance": False,
    "accounting_aggregation_authorized": False,
}
if args.output:
    output = args.output.resolve()
    if output.drive.lower() != "d:":
        raise ValueError("Acceptance artifacts must stay on D:")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
print(json.dumps(result, ensure_ascii=False, indent=2))

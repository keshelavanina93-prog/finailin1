"""Prepare authentic non-posting SOG header-count analysis over existing authority.

Default is read-only. After the API source is frozen, --apply performs ordinary
separate-actor publication and invokes the exact installed Function manifest.
No schema, accounting interpretation, source row or company identity is created.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid5

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import function_execution, function_invocations, resources

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
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
    and p.scope == maker.scope
    and {"ontology_admin", "ontology_review"} <= set(p.permissions)
)
company_id = UUID("c6f87828-9609-5b35-afa6-e894a0acfe41")
source_evidence_id = "71f45f39-35fb-56c1-b4b7-61e7edc56368"
source_sha256 = "45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d"
selected = {
    "2bd64825-e320-5039-b163-2064a1a71c82": ("Department", "AA"),
    "2cc5e885-54f5-5b58-9359-29fd06bf8eac": ("Budget Article New", "Z"),
    "7959af7f-a1bb-5573-8006-d1fc14f58681": ("Region", "Y"),
}
reason = (
    "Review existing authentic SOG source dimension header observations as a bounded "
    "non-posting metadata analysis. Count retained headers only; no transaction totals, "
    "financial classifications, operational activity or complete source coverage is inferred."
)


def read(identity):
    return resources.get_resource(maker, UUID(str(identity)))["resource"]


company = read(company_id)
evidence = read(source_evidence_id)
assert (
    company["object_type"] == "LegalEntity" and company["authority_state"] == "APPROVED"
)
assert evidence["attributes"]["sha256"] == source_sha256
schema = read(
    canonical_id(maker.scope.tenant_id, "SchemaDefinition", "CompanyDimension")
)
observations = []
for identity, (header, column) in selected.items():
    row = read(identity)
    attrs = row["attributes"]
    assert (
        row["object_type"] == "CompanyDimension"
        and row["evidence_class"] == "SOURCE_BOUND"
    )
    assert row["authority_state"] == "APPROVED"
    assert (
        attrs["legal_entity_id"] == str(company_id)
        and attrs["evidence_id"] == source_evidence_id
    )
    assert attrs["source_header"] == header and attrs["source_column"] == column
    assert row["schema_version_id"] == schema["version_id"]
    record = read(attrs["source_record_id"])
    assert record["attributes"] == {
        "evidence_id": source_evidence_id,
        "coordinate": f"TR!{column}2",
    }
    observations.append(row)

set_id = uuid5(company_id, "semantic-analysis:source-dimension-headers:object-set/v1")
function_id = uuid5(
    company_id, "semantic-analysis:source-dimension-headers:function/v1"
)
manifest = function_execution.manifest()
definition = {
    key: manifest[key]
    for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
}
definition.update(
    derived_property_ids=[],
    group_count={"schema_id": str(schema["resource_id"]), "fields": ["source_header"]},
)
plans = [
    (
        set_id,
        "ObjectSetDefinition",
        "Retained source dimension headers",
        {
            "definition": {
                "object_type": "CompanyDimension",
                "resource_ids": list(selected),
            }
        },
    ),
    (
        function_id,
        "FunctionDefinition",
        "SOG source dimension header counts",
        {
            "object_set_id": str(set_id),
            "definition": definition,
        },
    ),
]
published = []
for identity, kind, name, attributes in plans:
    prior = resources.current_resources(maker, [identity]).get(str(identity))
    if args.apply and (not prior or prior["attributes"] != attributes):
        proposal = ResourceProposal(
            title="Review non-posting source metadata analysis",
            rationale=reason,
            access_entity=maker.scope.legal_entity_id,
            mutations=[
                ResourceMutation(
                    resource_id=identity,
                    expected_version_id=prior["version_id"] if prior else None,
                    object_type=kind,
                    identity_key="semantic-metadata-analysis:" + str(identity),
                    display_name=name,
                    attributes=attributes,
                    valid_from=datetime.now(UTC),
                    evidence_class="USER_ASSERTED",
                )
            ],
            source_versions={
                identity: {
                    UUID(row["resource_id"]): UUID(row["version_id"])
                    for row in observations
                }
            },
        )
        resources.propose(maker, proposal)
        resources.review(
            checker,
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale=reason),
        )
        published.append(str(proposal.proposal_id))
result = {
    "mode": "APPLIED" if args.apply else "READ_ONLY_PREPARATION",
    "company_id": str(company_id),
    "source_sha256": source_sha256,
    "object_set_id": str(set_id),
    "function_id": str(function_id),
    "observations": [
        {key: row[key] for key in ("resource_id", "version_id", "content_hash")}
        for row in observations
    ],
    "grouping_fields": ["source_header"],
    "expected_observation_count": 3,
    "measure_authority": "OBSERVATION_COUNTS_ONLY",
    "financial_authority_established": False,
    "publication_proposals": published,
    "requires_frozen_source_before_apply": True,
}
if args.apply:
    function = read(function_id)
    # Stable per immutable Function version. A retry reopens the same receipt,
    # even when wall-clock time advanced; a reviewed new version gets a new run.
    frozen_at = datetime.fromisoformat(str(function["system_from"]))
    invocation = FunctionInvocation(
        request_id=uuid5(
            UUID(str(function["version_id"])), "semantic-metadata-analysis/1"
        ),
        function={"resource_id": function_id, "version_id": function["version_id"]},
        valid_at=frozen_at,
        known_at=frozen_at,
        offset=0,
        limit=10,
    )
    from finai_api.services.workspace import WorkspaceError

    try:
        history = function_invocations.history(maker, invocation.request_id)
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
        history = function_invocations.invoke(maker, invocation)
    if history["status"] == "INTENT_RETAINED":
        history = function_invocations.invoke(maker, invocation)
    assert history["status"] == "SUCCEEDED", history["receipt"].get("failure_code")
    counts = history["output"]["group_counts"]
    assert counts["object_count"] == 3 and len(counts["groups"]) == 3
    assert all(group["count"] == 1 for group in counts["groups"])
    result["invocation"] = {
        "invocation_id": history["invocation_id"],
        "receipt_hash": history["receipt_hash"],
        "run_id": history["output"]["run_id"],
        "function": history["output"]["function"],
    }
print(json.dumps(result, ensure_ascii=False, indent=2))

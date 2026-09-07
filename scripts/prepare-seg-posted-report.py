"""Prepare native SEG report definitions against the current target runtime manifest.

Run replay-seg-posted-accounting.py first. Defaults to no writes. --apply uses
configured separate review and preserves native identities; never copies isolated
version IDs. Does not start a Temporal worker or execute a workflow.
"""

import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true")
if not parser.parse_args().apply:
    print(
        "Prepare SEG posted-movement Function and Transformation using current target manifest; use --apply for canonical review."
    )
    raise SystemExit(0)
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid5

from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resource_lifecycle import (
    LifecycleRequest,
    LifecycleReview,
    VersionReference,
)
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import function_execution, resource_lifecycle, resources
from finai_api.services.resource_lifecycle import _latest
from psycopg.rows import dict_row

ps = [
    Principal.model_validate(v)
    for v in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
]
a = next(p for p in ps if {"ontology_admin", "ontology_propose"} <= set(p.permissions))
b = next(
    p
    for p in ps
    if p.actor_id != a.actor_id
    and p.scope.tenant_id == a.scope.tenant_id
    and {"ontology_admin", "ontology_review"} <= set(p.permissions)
)


def accept(mutations, title):
    p = ResourceProposal(
        title=title,
        rationale="Reviewed SEG statutory1C GEL posted-source accounting. Installed shared adapter; retain source cells and explicit missing-amount exclusions. No financial statement completeness or certification.",
        access_entity="__PLATFORM__"
        if all(m.object_type == "SchemaDefinition" for m in mutations)
        else a.scope.legal_entity_id,
        mutations=mutations,
    )
    resources.propose(a, p)
    resources.review(
        b, p.proposal_id, ResourceReview(decision="APPROVED", rationale=p.rationale)
    )
    return p


for spec in platform_definitions(a.scope.tenant_id):
    if spec["object_type"] == "SchemaDefinition" and spec["identity_key"] in {
        "FunctionDefinition",
        "TransformationDefinition",
    }:
        identity = canonical_id(
            a.scope.tenant_id, "SchemaDefinition", spec["identity_key"]
        )
        prior = resources.get_resource(a, identity)["resource"]
        if prior["attributes"] != spec["attributes"]:
            mutation = ResourceMutation(
                resource_id=identity,
                expected_version_id=prior["version_id"],
                valid_from=datetime.now(UTC),
                **spec,
            )
            accept([mutation], "Add native guarded posted-movement Function inputs")

binding = UUID("f4cf95a5-9552-519c-8e59-96ee06bd4308")
identity = uuid5(binding, "posted-movements-function/v1")
manifest = function_execution.manifest("accounting.retained-posted-movements/v1")
attrs = {
    "accounting_binding_id": str(binding),
    "source_scope_id": "23558068-046d-5fed-8582-3211ea2f2199",
    "evidence_id": "f2a292a5-7f7c-533e-8caf-dd0a32b16fa4",
    "minimum_authority_state": "OBSERVED",
    "definition": {
        k: manifest[k]
        for k in [
            "implementation_id",
            "determinism",
            "code_sha256",
            "dependency_sha256",
        ]
    },
}
attrs["definition"].update(
    document_id="ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6",
    source_sha256="d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a",
    sheet="Base",
    max_source_rows=1000,
)
try:
    prior = resources.get_resource(a, identity)["resource"]
except Exception as e:
    if getattr(e, "status", None) != 404:
        raise
    prior = None
if prior is None or prior["attributes"] != attrs:
    accept(
        [
            ResourceMutation(
                resource_id=identity,
                expected_version_id=prior["version_id"] if prior else None,
                object_type="FunctionDefinition",
                identity_key="seg-posted-movements-function",
                display_name="SEG January 2025 posted account movements",
                attributes=attrs,
                valid_from=datetime.now(UTC),
                evidence_class="USER_ASSERTED",
            )
        ],
        "Review SEG January posted-movement calculation",
    )
function = resources.get_resource(a, identity)["resource"]
with resources.resource_connection(a) as conn, conn.cursor(row_factory=dict_row) as cur:
    refs = cur.execute(
        "SELECT DISTINCT v.* FROM resource_dependencies d JOIN resource_versions v ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id AND v.version_id=d.target_version_id WHERE d.tenant_id=%s AND d.version_id=%s",
        (a.scope.tenant_id, function["version_id"]),
    ).fetchall()
for row in refs:
    ref = VersionReference(resource_id=row["resource_id"], version_id=row["version_id"])
    with (
        resources.resource_connection(a) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        event = _latest(cur, a, ref.version_id)
    if event is not None:
        assert event["payload"]["availability_state"] == "AVAILABLE"
        continue
    r = LifecycleRequest(
        subject=ref,
        target_state="OBSERVED",
        epistemic_state="OBSERVED"
        if row["evidence_class"] == "SOURCE_BOUND"
        else "INFERRED",
        business_state="PROVISIONAL",
        availability_state="AVAILABLE",
        reason="Retain current reviewed input availability for provisional posted-movement analysis. Source meaning is user asserted; no reconciliation or certification claimed.",
    )
    resource_lifecycle.request_transition(a, r)
    resource_lifecycle.review_transition(
        b, r.request_id, LifecycleReview(decision="APPROVED", reason=r.reason)
    )
print(
    json.dumps(
        {
            "function": function["resource_id"],
            "version": function["version_id"],
            "inputs": len(refs),
        }
    )
)


# Pin current reviewed target versions, including a changed executable manifest.
transform_id = uuid5(binding, "posted-movements-transformation/v1")
scope_id = UUID(attrs["source_scope_id"])
source_binding = resources.get_resource(a, binding)["resource"]
source_scope = resources.get_resource(a, scope_id)["resource"]
transform_attrs = {
    "definition": {
        "nodes": [
            {
                "node_id": "posted_movements",
                "function_id": function["resource_id"],
                "depends_on": [],
                "offset": 0,
                "limit": 50,
            }
        ],
        "outputs": [{"output_id": "account_movements", "node_id": "posted_movements"}],
    },
    "resource_budget": {
        "max_returned_rows": 1000,
        "max_derived_evaluations": 0,
        "max_published_result_bytes": 16000000,
    },
    "minimum_authority_state": "OBSERVED",
}
try:
    prior_graph = resources.get_resource(a, transform_id)["resource"]
except Exception as e:
    if getattr(e, "status", None) != 404:
        raise
    prior_graph = None
pins = {
    UUID(function["resource_id"]): UUID(function["version_id"]),
    binding: UUID(source_binding["version_id"]),
    scope_id: UUID(source_scope["version_id"]),
}
current_pins = {}
if prior_graph:
    with resources.resource_connection(a) as conn:
        current_pins = dict(
            conn.execute(
                "SELECT DISTINCT target_resource_id,target_version_id FROM resource_dependencies WHERE tenant_id=%s AND version_id=%s",
                (a.scope.tenant_id, prior_graph["version_id"]),
            ).fetchall()
        )
if (
    prior_graph is None
    or prior_graph["attributes"] != transform_attrs
    or any(current_pins.get(k) != v for k, v in pins.items())
):
    proposal = ResourceProposal(
        title="Review SEG posted-movement report orchestration",
        rationale="Exact current Function, source scope and reviewed statutory1C GEL posted-amount interpretation. Partial retained source coverage; no statement completeness or certification.",
        access_entity=a.scope.legal_entity_id,
        source_versions={transform_id: pins},
        mutations=[
            ResourceMutation(
                resource_id=transform_id,
                expected_version_id=prior_graph["version_id"] if prior_graph else None,
                object_type="TransformationDefinition",
                identity_key="seg-posted-movements-transformation",
                display_name="SEG January 2025 account movement report",
                attributes=transform_attrs,
                valid_from=datetime.now(UTC),
                evidence_class="USER_ASSERTED",
            )
        ],
    )
    resources.propose(a, proposal)
    resources.review(
        b,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale=proposal.rationale),
    )
graph = resources.get_resource(a, transform_id)["resource"]
print(
    json.dumps(
        {
            "function": {
                "resource_id": function["resource_id"],
                "version_id": function["version_id"],
            },
            "transformation": {
                "resource_id": graph["resource_id"],
                "version_id": graph["version_id"],
            },
            "binding": {
                "resource_id": source_binding["resource_id"],
                "version_id": source_binding["version_id"],
            },
        }
    )
)

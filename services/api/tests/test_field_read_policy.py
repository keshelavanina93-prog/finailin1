import os
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import (
    ConsumptionRequest,
    LifecycleRequest,
    LifecycleReview,
    VersionReference,
)
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resource_lifecycle, resources
from finai_api.services.workspace import WorkspaceError


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_restricted_field_propagates_through_derived_resources_and_proofs() -> None:
    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    p = Principal(
        actor_id="synthetic-cleared-author",
        display_name="Synthetic cleared author",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="classified-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=(
            "ontology_read",
            "ontology_admin",
            "ontology_propose",
            "ontology_review",
            "restricted_read",
        ),
    )
    reviewer = p.model_copy(update={"actor_id": "synthetic-cleared-reviewer"})
    uncleared = p.model_copy(
        update={
            "permissions": tuple(value for value in p.permissions if value != "restricted_read")
        }
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    source_kind = "PrivateValue" + uuid4().hex[:10]
    derived_kind = "DerivedValue" + uuid4().hex[:10]

    def field(semantic, kind, **extra):
        return {
            "field_id": str(uuid4()),
            "semantic_id": str(canonical_id(tenant, "SemanticContract", semantic)),
            "kind": kind,
            "required": True,
            **extra,
        }

    source_schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=source_kind,
        display_name="Protected canonical field",
        access_entity="__PLATFORM__",
        valid_from=start,
        attributes={
            "additional_fields": False,
            "fields": {
                "secret": field(
                    "Text", "text", required=False, read_permissions=["restricted_read"]
                )
            },
        },
    )
    derived_schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=derived_kind,
        display_name="Derived canonical contract",
        access_entity="__PLATFORM__",
        valid_from=start,
        attributes={
            "additional_fields": False,
            "fields": {
                "source_id": field("CanonicalReference", "reference", target_type=source_kind),
                "minimum_authority_state": field("Identifier", "identifier"),
            },
        },
    )
    source = ResourceMutation(
        object_type=source_kind,
        identity_key="synthetic:" + uuid4().hex,
        display_name="Synthetic protected observation",
        access_entity=p.scope.legal_entity_id,
        valid_from=start,
        attributes={"secret": "SYNTHETIC-RESTRICTED-VALUE"},
    )
    derived = ResourceMutation(
        object_type=derived_kind,
        identity_key="synthetic:" + uuid4().hex,
        display_name="Synthetic derived consumer",
        access_entity=p.scope.legal_entity_id,
        valid_from=start,
        attributes={"source_id": str(source.resource_id), "minimum_authority_state": "OBSERVED"},
    )
    proposal = ResourceProposal(
        title="Synthetic classified derivation",
        rationale="Independent field policy acceptance",
        access_entity="__TENANT__",
        mutations=[source_schema, derived_schema, source, derived],
    )
    resources.propose(p, proposal)
    with pytest.raises(WorkspaceError):
        resources.proposal_detail(uncleared, proposal.proposal_id)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent classified definition review"),
    )
    assert (
        resources.get_resource(p, source.resource_id)["resource"]["attributes"]["secret"]
        == "SYNTHETIC-RESTRICTED-VALUE"
    )
    for item in (source, derived):
        with pytest.raises(WorkspaceError):
            resources.get_resource(uncleared, item.resource_id)
    refs = [
        VersionReference(
            resource_id=item.resource_id,
            version_id=uuid5(proposal.proposal_id, str(item.resource_id)),
        )
        for item in (source, derived_schema)
    ]
    for ref in refs:
        request = LifecycleRequest(
            subject=ref,
            target_state="OBSERVED",
            epistemic_state="OBSERVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Explicit synthetic observed-state evidence",
        )
        resource_lifecycle.request_transition(p, request)
        resource_lifecycle.review_transition(
            reviewer,
            request.request_id,
            LifecycleReview(decision="APPROVED", reason="Independent observation review"),
        )
    consumption = ConsumptionRequest(
        consumer=VersionReference(
            resource_id=derived.resource_id,
            version_id=uuid5(proposal.proposal_id, str(derived.resource_id)),
        ),
        inputs=refs,
        minimum_state="OBSERVED",
    )
    proof = resource_lifecycle.consume(p, consumption)
    assert any(
        item["attributes"].get("secret") == "SYNTHETIC-RESTRICTED-VALUE" for item in proof["inputs"]
    )
    with pytest.raises(WorkspaceError):
        resource_lifecycle.consume(uncleared, consumption)
    with pytest.raises(WorkspaceError):
        resource_lifecycle.consumption_receipt(uncleared, consumption.request_id)
    with pytest.raises(WorkspaceError):
        resource_lifecycle.consumption_status(uncleared, consumption.request_id)
    with resources.resource_connection(uncleared) as conn:
        assert (
            conn.execute(
                "SELECT public.g8_has_hidden_current_dependents(%s)", (derived_schema.resource_id,)
            ).fetchone()[0]
            is True
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM canonical_identities WHERE tenant_id=%s AND resource_id=%s",
                (tenant, source.resource_id),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM resource_decisions WHERE tenant_id=%s AND proposal_id=%s",
                (tenant, proposal.proposal_id),
            ).fetchone()[0]
            == 0
        )
    # Removing the protected property does not declassify its retained before-value.
    removal = ResourceProposal(
        title="Remove optional protected property",
        rationale="Synthetic historical policy regression",
        access_entity="__TENANT__",
        mutations=[
            source.model_copy(
                update={
                    "expected_version_id": uuid5(proposal.proposal_id, str(source.resource_id)),
                    "attributes": {},
                }
            )
        ],
    )
    resources.propose(p, removal)
    with pytest.raises(WorkspaceError):
        resources.proposal_detail(uncleared, removal.proposal_id)
    # Public schema metadata can have protected downstream impact.
    schema_change = ResourceProposal(
        title="Clarify derived schema label",
        rationale="Synthetic downstream impact policy regression",
        access_entity="__TENANT__",
        mutations=[
            derived_schema.model_copy(
                update={
                    "expected_version_id": uuid5(
                        proposal.proposal_id, str(derived_schema.resource_id)
                    ),
                    "display_name": "Clarified derived schema",
                }
            )
        ],
    )
    resources.propose(p, schema_change)
    with pytest.raises(WorkspaceError):
        resources.proposal_detail(uncleared, schema_change.proposal_id)
    with pytest.raises(WorkspaceError):
        resources.propose(uncleared, schema_change.model_copy(update={"proposal_id": uuid4()}))

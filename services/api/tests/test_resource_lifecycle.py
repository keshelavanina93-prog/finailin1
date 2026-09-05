"""Native PostgreSQL lifecycle contract; synthetic definitions are not certified facts."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from psycopg.rows import dict_row

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
from finai_api.services import resource_lifecycle as lifecycle
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

pytestmark = pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained DB acceptance"
)


def test_reviewed_authority_current_guard_and_retained_history():
    p = Principal(
        actor_id="synthetic-lifecycle-author",
        display_name="Synthetic lifecycle",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-lifecycle-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_admin", "ontology_read", "ontology_propose", "ontology_review"),
    )
    reviewer = p.model_copy(update={"actor_id": "synthetic-lifecycle-reviewer"})
    # A LinkType is a canonical consumer with exact accepted schema pins. Its additional
    # attributes carry the explicit consumer minimum without inventing execution behavior.
    key = "LifecycleConsumer" + uuid4().hex[:10]
    schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=key,
        display_name="Synthetic lifecycle consumer schema",
        access_entity="__PLATFORM__",
        attributes={
            "additional_fields": True,
            "fields": {
                "minimum_authority_state": {
                    "field_id": str(uuid4()),
                    "semantic_id": str(
                        canonical_id(p.scope.tenant_id, "SemanticContract", "Identifier")
                    ),
                    "kind": "identifier",
                    "required": True,
                }
            },
        },
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    consumer = ResourceMutation(
        object_type=key,
        identity_key="synthetic:" + uuid4().hex,
        display_name="Synthetic authority consumer",
        attributes={"minimum_authority_state": "AUTHORITATIVE"},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    proposal = ResourceProposal(
        title="Synthetic lifecycle definitions",
        rationale="Focused explicit authority acceptance",
        access_entity="__TENANT__",
        mutations=[schema, consumer],
    )
    resources.propose(p, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic registry approval"),
    )
    cv = resources.get_resource(p, consumer.resource_id)["resource"]
    with resources.resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        pins = c.execute(
            "SELECT target_resource_id,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s",
            (p.scope.tenant_id, cv["version_id"]),
        ).fetchall()
    refs = [
        VersionReference(resource_id=x["target_resource_id"], version_id=x["target_version_id"])
        for x in pins
    ]
    assert len(refs) == 1
    ref = refs[0]
    request = ConsumptionRequest(
        consumer=VersionReference(resource_id=consumer.resource_id, version_id=cv["version_id"]),
        inputs=refs,
        minimum_state="OBSERVED",
    )
    with pytest.raises(WorkspaceError, match="required authority"):
        lifecycle.consume(p, request)
    event = None

    def advance(state, availability="AVAILABLE"):
        nonlocal event
        draft = LifecycleRequest(
            subject=ref,
            expected_event_id=event,
            target_state=state,
            epistemic_state="INFERRED",
            business_state="PROVISIONAL",
            availability_state=availability,
            reason="Explicit synthetic lifecycle rationale",
        )
        lifecycle.request_transition(p, draft)
        with pytest.raises(WorkspaceError, match="Independent"):
            lifecycle.review_transition(
                p,
                draft.request_id,
                LifecycleReview(decision="APPROVED", reason="Same actor must not approve"),
            )
        lifecycle.review_transition(
            reviewer,
            draft.request_id,
            LifecycleReview(decision="APPROVED", reason="Independent synthetic lifecycle review"),
        )
        event = lifecycle.history(p, ref)["events"][-1]["event_id"]

    for state in lifecycle.ORDER[:3]:
        advance(state)
    with pytest.raises(WorkspaceError, match="required authority"):
        lifecycle.consume(p, request)
    for state in lifecycle.ORDER[3:]:
        advance(state)
    result = lifecycle.consume(p, request)
    assert result["minimum_state"] == "AUTHORITATIVE"
    assert result["inputs"][0]["epistemic_state"] == "INFERRED"
    assert result["inputs"][0]["access_entity"] == "__PLATFORM__"
    accepted_time = lifecycle.history(p, ref)["events"][-1]["recorded_at"]
    advance("AUTHORITATIVE", "STALE")
    with pytest.raises(WorkspaceError, match="required authority and availability"):
        lifecycle.consume(p, request)
    historical = lifecycle.history(p, ref, accepted_time)
    assert historical["state"]["target_state"] == "AUTHORITATIVE"
    assert historical["state"]["availability_state"] == "AVAILABLE"
    assert lifecycle.history(p, ref)["state"]["availability_state"] == "STALE"
    advance("AUTHORITATIVE", "AVAILABLE")
    assert lifecycle.consume(p, request)["inputs"][0]["availability_state"] == "AVAILABLE"
    advance("REVOKED")
    with pytest.raises(WorkspaceError, match="required authority and availability"):
        lifecycle.consume(p, request)
    # Terminal consumer lifecycle denies its own current use independently of its inputs.
    consumer_event = None
    for state in ("OBSERVED", "REVOKED"):
        draft = LifecycleRequest(
            subject=request.consumer,
            expected_event_id=consumer_event,
            target_state=state,
            epistemic_state="DERIVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Withdraw synthetic consumer authority",
        )
        lifecycle.request_transition(p, draft)
        lifecycle.review_transition(
            reviewer,
            draft.request_id,
            LifecycleReview(decision="APPROVED", reason="Independent consumer withdrawal"),
        )
        consumer_event = lifecycle.history(p, request.consumer)["events"][-1]["event_id"]
    with pytest.raises(WorkspaceError, match="withdrawn"):
        lifecycle.consume(p, request)
    with pytest.raises(WorkspaceError, match="withdrawn"):
        lifecycle.consume(p, request)
    assert [x["payload"]["target_state"] for x in lifecycle.history(p, ref)["events"]] == [
        *lifecycle.ORDER,
        "AUTHORITATIVE",
        "AUTHORITATIVE",
        "REVOKED",
    ]
    other = p.model_copy(
        update={
            "permissions": ("ontology_read",),
            "scope": p.scope.model_copy(update={"legal_entity_id": "other-company"}),
        }
    )
    with pytest.raises(WorkspaceError, match="authorized context"):
        lifecycle.consume(other, request)

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.domain.source_event import SourceEvent
from finai_api.services import event_time, resources
from finai_api.services.workspace import WorkspaceError


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_retained_lateness_deterministic_replay_and_scope() -> None:
    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    p = Principal(
        actor_id="synthetic-event-author",
        display_name="Synthetic stream author",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="stream-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=(
            "ontology_read",
            "ontology_admin",
            "ontology_propose",
            "ontology_review",
            "ingest",
        ),
    )
    reviewer = p.model_copy(update={"actor_id": "synthetic-event-reviewer"})
    kind = "EventStream" + uuid4().hex[:10]
    policy = {
        "event_time_policy_version": "event-time/1",
        "late_policy": "RETAIN_ONLY",
        "allowed_lateness_seconds": 30,
        "allowed_future_seconds": 0,
    }
    fields = {
        name: {
            "field_id": str(uuid4()),
            "semantic_id": str(
                canonical_id(
                    tenant, "SemanticContract", "Count" if type(value) is int else "Identifier"
                )
            ),
            "kind": "integer" if type(value) is int else "identifier",
            "required": True,
        }
        for name, value in policy.items()
    }
    base = datetime.now(UTC) - timedelta(days=1)
    schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=kind,
        display_name="Synthetic event policy",
        access_entity="__PLATFORM__",
        attributes={"fields": fields, "additional_fields": False},
        valid_from=base,
    )
    stream = ResourceMutation(
        object_type=kind,
        identity_key="synthetic:" + uuid4().hex,
        display_name="Synthetic observed stream",
        access_entity=p.scope.legal_entity_id,
        attributes=policy,
        valid_from=base,
    )
    proposal = ResourceProposal(
        title="Synthetic event time policy",
        rationale="Explicit reviewed observation timing",
        access_entity="__TENANT__",
        mutations=[schema, stream],
    )
    resources.propose(p, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent event policy review"),
    )
    ref = VersionReference(
        resource_id=stream.resource_id,
        version_id=uuid5(proposal.proposal_id, str(stream.resource_id)),
    )
    first = SourceEvent(
        stream=ref,
        event_id="a",
        partition_key="meter-a",
        event_time=base + timedelta(seconds=60),
        payload={"raw": "10"},
    )
    retained = event_time.retain_event(p, first)
    assert event_time.retain_event(p, first) == retained
    scheduled = ResourceProposal(
        title="Schedule a synthetic stream policy",
        rationale="A future policy must not interrupt the currently effective stream",
        access_entity=p.scope.legal_entity_id,
        mutations=[stream.model_copy(update={
            "expected_version_id": ref.version_id,
            "valid_from": datetime.now(UTC) + timedelta(days=30),
            "attributes": {**policy, "allowed_lateness_seconds": 300},
        })],
    )
    resources.propose(p, scheduled)
    resources.review(
        reviewer, scheduled.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Review synthetic future event policy"),
    )
    assert event_time.retain_event(p, first) == retained
    future_ref = VersionReference(
        resource_id=stream.resource_id,
        version_id=uuid5(scheduled.proposal_id, str(stream.resource_id)),
    )
    with pytest.raises(WorkspaceError, match="current use"):
        event_time.retain_event(
            p, first.model_copy(update={"stream": future_ref, "event_id": "premature-policy"})
        )
    with pytest.raises(WorkspaceError, match="different retained content"):
        event_time.retain_event(p, first.model_copy(update={"payload": {"raw": "11"}}))
    late = event_time.retain_event(
        p,
        first.model_copy(
            update={"event_id": "late", "partition_key": "meter-b", "event_time": base}
        ),
    )
    assert late["admission"] == "RETAINED_LATE"
    assert late["watermark"] == base + timedelta(seconds=30)
    assert late["stream_version_id"] == str(ref.version_id)
    event_time.retain_event(p, first.model_copy(update={"event_id": "z", "payload": {"raw": "12"}}))
    now = datetime.now(UTC)
    replayed = event_time.replay(p, stream.resource_id, now)
    assert replayed == event_time.replay(p, stream.resource_id, now)
    assert replayed["projection"][0]["event_id"] == "z"
    assert replayed["late_event_count"] == 1
    assert replayed["authority_state"] == "OBSERVED" and replayed["current_use_authorized"] is False
    old = event_time.replay(p, stream.resource_id, retained["processing_time"])
    assert old["event_count"] == 1 and old["projection"][0]["event_id"] == "a"
    backfill = event_time.replay(p, stream.resource_id, now, include_late=True)
    assert backfill["purpose"] == "BACKFILL_OBSERVATION" and len(backfill["projection"]) == 2
    with pytest.raises(WorkspaceError, match="future-time"):
        event_time.retain_event(
            p,
            first.model_copy(update={"event_id": "future", "event_time": now + timedelta(days=1)}),
        )
    other = p.model_copy(
        update={
            "permissions": ("ontology_read",),
            "scope": p.scope.model_copy(update={"legal_entity_id": "other"}),
        }
    )
    with pytest.raises(WorkspaceError, match="authorized context"):
        event_time.replay(other, stream.resource_id, now)

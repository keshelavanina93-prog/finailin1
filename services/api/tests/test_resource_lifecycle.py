"""Native PostgreSQL lifecycle contract; synthetic definitions are not certified facts."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.authority import ExactScope
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
    semantic = ResourceMutation(
        object_type="SemanticContract",
        identity_key="synthetic-lifecycle-meaning:" + uuid4().hex,
        display_name="Synthetic consumer authority meaning",
        access_entity="__PLATFORM__",
        attributes={"kind": "identifier"},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
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
                    "semantic_id": str(semantic.resource_id),
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
        mutations=[semantic, schema, consumer],
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
    assert lifecycle.consume(p, request) == result
    retained = lifecycle.consumption_receipt(p, request.request_id)
    assert retained["proof_hash"] == result["proof_hash"]
    assert retained["current_use_authorized"] is False
    assert len(result["upstream_authority"]) == 2
    # Scheduling successors changes editing heads, not today's effective authority.
    future_at = datetime.now(UTC) + timedelta(days=30)
    scheduled = []
    for original in (semantic, schema, consumer):
        head = resources.get_resource(p, original.resource_id)["resource"]
        scheduled.append(
            original.model_copy(
                update={
                    "expected_version_id": UUID(head["version_id"]),
                    "display_name": original.display_name + " scheduled successor",
                    "valid_from": future_at,
                }
            )
        )
    scheduled_proposal = ResourceProposal(
        title="Schedule synthetic future definitions",
        rationale="Future publication must preserve current effective consumption",
        access_entity="__TENANT__",
        mutations=scheduled,
    )
    resources.propose(p, scheduled_proposal)
    resources.review(
        reviewer,
        scheduled_proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Review future synthetic definitions"),
    )
    future_consumer = resources.get_resource(p, consumer.resource_id)["resource"]
    assert future_consumer["version_id"] != cv["version_id"]
    assert lifecycle.consume(p, request) == result
    # A fresh receipt also exercises all SQL insertion guards after scheduling.
    fresh = lifecycle.consume(p, request.model_copy(update={"request_id": uuid4()}))
    assert fresh["consumer"]["version_id"] == str(cv["version_id"])
    future_ref = VersionReference(
        resource_id=consumer.resource_id, version_id=future_consumer["version_id"]
    )
    with resources.resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        with pytest.raises(WorkspaceError, match="current use"):
            lifecycle._version(cursor, p, future_ref)
        # Boundary selection is deterministic without advancing wall-clock time.
        assert cursor.execute(
            "SELECT g8_effective_version_id(%s,%s,%s) AS version",
            (p.scope.tenant_id, consumer.resource_id, future_at),
        ).fetchone()["version"] == UUID(future_consumer["version_id"])
        forged_future = {
            **fresh,
            "consumption_id": str(uuid4()),
            "consumer": future_ref.model_dump(mode="json"),
            "consumer_content_hash": future_consumer["content_hash"],
        }
        with (
            pytest.raises(psycopg.Error, match="Invalid canonical consumption"),
            conn.transaction(),
        ):
            cursor.execute(
                "INSERT INTO guarded_consumption_receipts "
                "(tenant_id,consumption_id,consumer_resource_id,consumer_version_id,access_entity,"
                "actor_id,request_hash,proof_hash,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    p.scope.tenant_id, forged_future["consumption_id"], consumer.resource_id,
                    future_ref.version_id, fresh["access_entity"], p.actor_id, "0" * 64,
                    "0" * 64, Jsonb(forged_future),
                ),
            )
    current_check = lifecycle.consumption_status(p, request.request_id)
    assert current_check["status"] == "RECHECK_REQUIRED"
    assert current_check["current_use_authorized"] is False
    assert not any(item["blocker"] for item in current_check["checks"])
    with resources.resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        with pytest.raises(psycopg.Error), conn.transaction():
            cursor.execute(
                "DELETE FROM guarded_consumption_receipts WHERE tenant_id=%s AND consumption_id=%s",
                (p.scope.tenant_id, request.request_id),
            )
        forged = {
            **retained["proof"],
            "consumption_id": str(uuid4()),
            "inputs": [{**retained["proof"]["inputs"][0], "epistemic_state": "OBSERVED"}],
        }
        with pytest.raises(psycopg.Error, match="state differs"), conn.transaction():
            cursor.execute(
                "INSERT INTO guarded_consumption_receipts "
                "(tenant_id,consumption_id,consumer_resource_id,consumer_version_id,access_entity,"
                "actor_id,request_hash,proof_hash,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    p.scope.tenant_id,
                    forged["consumption_id"],
                    request.consumer.resource_id,
                    request.consumer.version_id,
                    result["access_entity"],
                    p.actor_id,
                    "0" * 64,
                    "0" * 64,
                    Jsonb(forged),
                ),
            )
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
    with pytest.raises(WorkspaceError, match="authority changed"):
        lifecycle.consume(p, request)
    request = request.model_copy(update={"request_id": uuid4()})
    assert lifecycle.consume(p, request)["inputs"][0]["availability_state"] == "AVAILABLE"
    ancestor = next(
        item for item in result["upstream_authority"]
        if item["resource_id"] == str(semantic.resource_id)
    )
    ancestor_ref = VersionReference(
        resource_id=semantic.resource_id, version_id=ancestor["version_id"]
    )
    ancestor_event = None
    for state in ("OBSERVED", "REVOKED"):
        withdrawal = LifecycleRequest(
            subject=ancestor_ref,
            expected_event_id=ancestor_event,
            target_state=state,
            epistemic_state="OBSERVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Synthetic upstream semantic withdrawal",
        )
        lifecycle.request_transition(p, withdrawal)
        lifecycle.review_transition(
            reviewer,
            withdrawal.request_id,
            LifecycleReview(decision="APPROVED", reason="Independent upstream withdrawal review"),
        )
        ancestor_event = lifecycle.history(p, ancestor_ref)["events"][-1]["event_id"]
    with pytest.raises(WorkspaceError, match="Upstream dependency authority"):
        lifecycle.consume(p, request)
    withdrawal_check = lifecycle.consumption_status(p, UUID(result["consumption_id"]))
    assert withdrawal_check["status"] == "BLOCKED"
    assert any(
        item["subject"]["resource_id"] == str(semantic.resource_id)
        and item["blocker"] == "AUTHORITY_WITHDRAWN"
        for item in withdrawal_check["checks"]
    )
    advance("REVOKED")
    assert lifecycle.consumption_receipt(p, UUID(result["consumption_id"])) == retained
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
    with pytest.raises(WorkspaceError, match="authorized context"):
        lifecycle.consumption_receipt(other, UUID(result["consumption_id"]))
    with pytest.raises(WorkspaceError, match="authorized context"):
        lifecycle.consumption_status(other, UUID(result["consumption_id"]))
    # A registry revocation effective now wins over the prior approved interval,
    # even though a separately published successor has a future effective date.
    editing_head = resources.get_resource(p, semantic.resource_id)["resource"]
    revoked = semantic.model_copy(
        update={
            "expected_version_id": UUID(editing_head["version_id"]),
            "valid_from": datetime.now(UTC),
            "authority_state": "REVOKED",
        }
    )
    withdrawal = ResourceProposal(
        title="Revoke current synthetic semantic meaning",
        rationale="A revoked temporal winner must never resurrect approved history",
        access_entity="__TENANT__",
        mutations=[revoked],
    )
    resources.propose(p, withdrawal)
    resources.review(
        reviewer, withdrawal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Review synthetic registry withdrawal"),
    )
    revoked_head = resources.get_resource(p, semantic.resource_id)["resource"]
    with resources.resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        winner = cursor.execute(
            "SELECT g8_effective_version_id(%s,%s,clock_timestamp()) AS version",
            (p.scope.tenant_id, semantic.resource_id),
        ).fetchone()["version"]
        assert winner == UUID(revoked_head["version_id"])
        assert winner != ancestor_ref.version_id
        for rejected in (
            ancestor_ref,
            VersionReference(resource_id=semantic.resource_id, version_id=winner),
        ):
            with pytest.raises(WorkspaceError, match="current use"):
                lifecycle._version(cursor, p, rejected)
        # Historical access still resolves the exact earlier immutable version.
        assert lifecycle._version(cursor, p, ancestor_ref, current=False)["version_id"] == (
            ancestor_ref.version_id
        )

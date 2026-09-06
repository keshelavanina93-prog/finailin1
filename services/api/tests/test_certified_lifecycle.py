# ruff: noqa: F811
"""Reviewed structural certification transitions on synthetic canonical definitions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_certification import fixture
from test_definition_history import DB, retained  # noqa: F401

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.resource_lifecycle import LifecycleRequest, LifecycleReview
from finai_api.services import certification, resources
from finai_api.services import resource_lifecycle as lifecycle
from finai_api.services.workspace import WorkspaceError


def ready(retained):
    reader, publish, _subject, contract, evaluation = fixture(retained)
    p = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
            )
        }
    )
    reviewer = p.model_copy(update={"actor_id": "synthetic-certification-lifecycle-reviewer"})
    receipt = certification.evaluate(p, evaluation)
    prior = None
    for state in lifecycle.ORDER:
        request = LifecycleRequest(
            subject=evaluation.subject,
            expected_event_id=prior,
            target_state=state,
            epistemic_state="DERIVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Synthetic independent structural authority",
        )
        lifecycle.request_transition(p, request)
        lifecycle.review_transition(
            reviewer,
            request.request_id,
            LifecycleReview(decision="APPROVED", reason="Independent synthetic authority review"),
        )
        prior = lifecycle.history(p, evaluation.subject)["events"][-1]["event_id"]
    request = LifecycleRequest(
        subject=evaluation.subject,
        expected_event_id=prior,
        target_state="CERTIFIED",
        epistemic_state="DERIVED",
        business_state="PROVISIONAL",
        availability_state="AVAILABLE",
        reason="Certify only exact definition structural conformance",
        certification_receipt_id=receipt["receipt_id"],
        certification_contract=evaluation.contract,
    )
    return p, reviewer, publish, contract, evaluation, request, receipt


@DB
def test_certified_requires_bound_receipt_independent_review_and_retains_proof(retained):
    p, reviewer, _, _, evaluation, request, receipt = ready(retained)
    bare = request.model_copy(
        update={"certification_receipt_id": None, "certification_contract": None}
    )
    with pytest.raises(WorkspaceError, match="exact receipt"):
        lifecycle.request_transition(p, bare)
    with (
        pytest.raises(psycopg.Error, match="exact receipt"),
        resources.resource_connection(p) as conn,
    ):
        conn.execute(
            "INSERT INTO resource_lifecycle_requests(tenant_id,request_id,resource_id,"
            "version_id,access_entity,submitted_by,request_hash,payload) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                p.scope.tenant_id,
                bare.request_id,
                bare.subject.resource_id,
                bare.subject.version_id,
                p.scope.legal_entity_id,
                p.actor_id,
                canonical_sha256(bare),
                Jsonb(bare.model_dump(mode="json")),
            ),
        )
    lifecycle.request_transition(p, request)
    with pytest.raises(WorkspaceError, match="Independent"):
        lifecycle.review_transition(
            p,
            request.request_id,
            LifecycleReview(decision="APPROVED", reason="Author cannot approve own certification"),
        )
    lifecycle.review_transition(
        reviewer,
        request.request_id,
        LifecycleReview(decision="APPROVED", reason="Independent exact certification review"),
    )
    event = lifecycle.history(p, evaluation.subject)["events"][-1]
    assert event["payload"]["target_state"] == "CERTIFIED"
    assert event["certification_proof_hash"] == receipt["proof_hash"]
    for availability in ("DEGRADED", "AVAILABLE"):
        amendment = request.model_copy(
            update={
                "request_id": uuid4(),
                "expected_event_id": event["event_id"],
                "availability_state": availability,
            }
        )
        lifecycle.request_transition(p, amendment)
        lifecycle.review_transition(
            reviewer,
            amendment.request_id,
            LifecycleReview(
                decision="APPROVED", reason="Review certification availability amendment"
            ),
        )
        event = lifecycle.history(p, evaluation.subject)["events"][-1]
        assert event["payload"]["availability_state"] == availability


@DB
def test_contract_revocation_rechecked_at_approval_and_withdrawal_still_allowed(retained):
    p, reviewer, publish, contract, evaluation, request, receipt = ready(retained)
    lifecycle.request_transition(p, request)
    lifecycle.review_transition(
        reviewer,
        request.request_id,
        LifecycleReview(decision="APPROVED", reason="Independent exact certification review"),
    )
    event = lifecycle.history(p, evaluation.subject)["events"][-1]
    amendment = request.model_copy(
        update={
            "request_id": uuid4(),
            "expected_event_id": event["event_id"],
            "business_state": "LIVE",
        }
    )
    lifecycle.request_transition(p, amendment)
    publish(
        contract.model_copy(
            update={
                "expected_version_id": evaluation.contract.version_id,
                "authority_state": "REVOKED",
                "valid_from": datetime.now(UTC) - timedelta(seconds=1),
            }
        )
    )
    with pytest.raises(WorkspaceError, match="current use"):
        lifecycle.review_transition(
            reviewer,
            amendment.request_id,
            LifecycleReview(
                decision="APPROVED", reason="Revoked contract must block fresh approval"
            ),
        )
    withdrawal = amendment.model_copy(update={"request_id": uuid4(), "target_state": "REVOKED"})
    lifecycle.request_transition(p, withdrawal)
    lifecycle.review_transition(
        reviewer,
        withdrawal.request_id,
        LifecycleReview(decision="APPROVED", reason="Withdraw subject after contract revocation"),
    )
    final = lifecycle.history(p, evaluation.subject)["events"][-1]
    assert final["payload"]["target_state"] == "REVOKED"
    assert final["certification_proof_hash"] == receipt["proof_hash"]

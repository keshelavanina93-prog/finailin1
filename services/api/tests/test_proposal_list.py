"""Bounded proposal queue preserves RLS, retained decisions and recency ordering."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


def actor():
    return Principal(
        actor_id="synthetic-queue-author",
        display_name="Synthetic queue author",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="queue-" + uuid4().hex,
            period="2026-09",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review"),
    )


@pytest.mark.parametrize("limit", [0, 101])
def test_queue_limit_checked_before_database(limit):
    with pytest.raises(WorkspaceError) as error:
        resources.proposals(actor(), limit)
    assert error.value.status == 422


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in PostgreSQL")
def test_queue_page_decisions_order_and_isolation():
    author = actor()
    with resources.resource_connection(author) as conn:
        prior_preference = conn.execute("SHOW enable_sort").fetchone()[0]
    reviewer = author.model_copy(update={"actor_id": "independent-queue-reviewer"})
    retained = []
    for decision in ("APPROVED", "REJECTED", "PENDING"):
        proposal = ResourceProposal(
            title="SYNTHETIC queue " + decision,
            rationale="Retained proposal listing correctness fixture",
            access_entity=author.scope.legal_entity_id,
            mutations=[
                ResourceMutation(
                    object_type="LegalEntity",
                    identity_key="synthetic:queue:" + uuid4().hex,
                    display_name="SYNTHETIC queue company",
                    attributes={},
                    valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                    evidence_class="REFERENCE_TEMPLATE",
                )
            ],
        )
        resources.propose(author, proposal)
        if decision != "PENDING":
            resources.review(
                reviewer,
                proposal.proposal_id,
                ResourceReview(decision=decision, rationale="Independent queue review"),
            )
        retained.append((proposal.proposal_id, decision))
    for size in (1, 2, 3):
        rows = resources.proposals(author, size)
        assert len(rows) == size
        assert [(row["proposal_id"], row["decision"]) for row in rows] == list(reversed(retained))[
            :size
        ]
        assert rows == sorted(
            rows, key=lambda row: (-row["created_at"].timestamp(), row["proposal_id"])
        )
        assert all(row["access_entity"] == author.scope.legal_entity_id for row in rows)
        assert all(row["submitted_by"] == author.actor_id and row["rationale"] for row in rows)
    outsider = author.model_copy(
        update={
            "scope": author.scope.model_copy(
                update={
                    "legal_entity_id": "unrelated-" + uuid4().hex,
                }
            )
        }
    )
    assert {row["proposal_id"] for row in resources.proposals(outsider)}.isdisjoint(
        identity for identity, _ in retained
    )
    empty_tenant = author.model_copy(
        update={
            "scope": author.scope.model_copy(
                update={
                    "tenant_id": uuid4(),
                }
            )
        }
    )
    assert resources.proposals(empty_tenant) == []
    with resources.resource_connection(author) as conn:
        assert conn.execute("SHOW enable_sort").fetchone()[0] == prior_preference

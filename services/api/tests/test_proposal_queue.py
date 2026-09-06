"""Native keyset paging keeps ties, cutoff and RLS without historical decision claims."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_proposal_list import actor

from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services import resources
from finai_api.services.proposal_queue import page
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"snapshot_at": datetime(2026, 1, 1)},
        {"before_created_at": datetime.now(UTC)},
        {"before_proposal_id": uuid4()},
        {"before_created_at": datetime(2026, 1, 1), "before_proposal_id": uuid4()},
    ],
)
def test_invalid_cursor_rejected_before_database(kwargs):
    with pytest.raises(WorkspaceError) as error:
        page(actor(), **kwargs)
    assert error.value.status == 422


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in PostgreSQL")
def test_native_equal_times_cutoff_decision_and_isolation():
    base = actor()
    author = base.model_copy(update={"scope": base.scope.model_copy(update={"tenant_id": uuid4()})})
    cutoff = datetime.now(UTC)
    identities = sorted([uuid4() for _ in range(4)])
    with resources.resource_connection(author) as conn:
        for index, identity in enumerate(identities):
            proposal = ResourceProposal(
                proposal_id=identity,
                title="SYNTHETIC paged queue",
                rationale="Paging fixture",
                access_entity=author.scope.legal_entity_id,
                mutations=[
                    ResourceMutation(
                        object_type="SchemaDefinition",
                        identity_key="synthetic:paging:" + uuid4().hex,
                        display_name="SYNTHETIC",
                        attributes={},
                        valid_from=cutoff,
                        evidence_class="REFERENCE_TEMPLATE",
                    )
                ],
            )
            conn.execute(
                "INSERT INTO resource_proposals "
                "(tenant_id,proposal_id,access_entity,submitted_by,title,rationale,"
                "request_hash,payload,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    author.scope.tenant_id,
                    identity,
                    author.scope.legal_entity_id,
                    author.actor_id,
                    proposal.title,
                    proposal.rationale,
                    uuid4().hex,
                    Jsonb({"request": proposal.model_dump(mode="json"), "validation": {}}),
                    cutoff if index < 3 else cutoff + timedelta(seconds=1),
                ),
            )
    first = page(author, 1, cutoff)
    assert first["proposals"][0]["proposal_id"] == identities[0]
    assert first["has_more"] and first["decision_mode"] == "CURRENT_RETAINED_DECISION"
    second = page(
        author,
        1,
        first["snapshot_at"],
        **{
            "before_created_at": first["next_cursor"]["created_at"],
            "before_proposal_id": first["next_cursor"]["proposal_id"],
        },
    )
    third = page(
        author,
        1,
        cutoff,
        **{
            "before_created_at": second["next_cursor"]["created_at"],
            "before_proposal_id": second["next_cursor"]["proposal_id"],
        },
    )
    assert [
        second["proposals"][0]["proposal_id"],
        third["proposals"][0]["proposal_id"],
    ] == identities[1:3]
    assert third["has_more"] is False and third["next_cursor"] is None
    assert len(page(author, 100, cutoff)["proposals"]) == 3
    assert all(row["decision"] == "PENDING" for row in first["proposals"])
    with resources.resource_connection(author) as conn:
        conn.execute(
            "INSERT INTO resource_decisions "
            "(tenant_id,proposal_id,access_entity,decision,reviewed_by,rationale) "
            "VALUES (%s,%s,%s,'REJECTED',%s,'Synthetic retained decision after cutoff')",
            (
                author.scope.tenant_id,
                identities[0],
                author.scope.legal_entity_id,
                "independent-queue-reviewer",
            ),
        )
    # The proposal window is frozen; the decision is deliberately current retained state.
    assert page(author, 1, cutoff)["proposals"][0]["decision"] == "REJECTED"
    outsider = author.model_copy(
        update={
            "scope": author.scope.model_copy(update={"legal_entity_id": "unrelated-" + uuid4().hex})
        }
    )
    assert page(outsider, 100, cutoff)["proposals"] == []
    alien = author.model_copy(
        update={"scope": author.scope.model_copy(update={"tenant_id": uuid4()})}
    )
    assert page(alien, 100, cutoff)["proposals"] == []

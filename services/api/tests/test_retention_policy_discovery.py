# ruff: noqa: F811
"""Policy discovery retains current meaning and bounded cursor progress."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from test_artifact_retention import policy_attributes, setup
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.artifact_retention import RetentionPolicyDiscoveryRequest
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import artifact_retention as retention
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


@DB
def test_current_policy_scope_holds_and_empty_page_progress(retained, monkeypatch):
    reader, publish, revoked, evaluation = setup(retained)
    held = item("RetentionPolicy", policy_attributes(hold=True, state="NOT_ESTABLISHED"))
    second = item("RetentionPolicy", policy_attributes())
    held_row, _ = publish(held, second)
    publish(
        held.model_copy(
            update={
                "expected_version_id": UUID(held_row["version_id"]),
                "attributes": policy_attributes(),
                "valid_from": datetime.now(UTC) + timedelta(days=10),
            }
        )
    )
    publish(
        revoked.model_copy(
            update={
                "expected_version_id": evaluation.policy.version_id,
                "authority_state": "REVOKED",
                "valid_from": datetime.now(UTC) - timedelta(seconds=1),
            }
        )
    )
    admin = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
            )
        }
    )
    other = item("RetentionPolicy", policy_attributes())
    proposal = ResourceProposal(
        title="Synthetic other-company policy",
        rationale="Prove exact company filter",
        access_entity="synthetic-other-" + uuid4().hex,
        mutations=[other],
    )
    resources.propose(admin, proposal)
    resources.review(
        admin.model_copy(update={"actor_id": "synthetic-policy-discovery-reviewer"}),
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic policy review"),
    )
    query = RetentionPolicyDiscoveryRequest(artifact=evaluation.artifact)
    page = retention.discover_policies(admin, query)
    assert {entry["reference"]["resource_id"] for entry in page["items"]} == {
        str(held.resource_id),
        str(second.resource_id),
    }
    old = next(
        entry
        for entry in page["items"]
        if entry["reference"]["resource_id"] == str(held.resource_id)
    )
    assert old["reference"]["version_id"] == held_row["version_id"]
    assert old["definition"]["legal_hold"] is True
    assert old["definition"]["legal_basis_state"] == "NOT_ESTABLISHED"
    assert page["execution_authorized"] is False
    first_id = min(held.resource_id, second.resource_id)
    actual_current = retention._current

    def unavailable_first(cursor, principal, reference):
        if reference.resource_id == first_id:
            raise WorkspaceError(409, "Synthetic current policy withdrawal")
        return actual_current(cursor, principal, reference)

    monkeypatch.setattr(retention, "_current", unavailable_first)
    first = retention.discover_policies(admin, query.model_copy(update={"limit": 1}))
    assert first["items"] == []
    assert first["next_cursor"] == str(first_id)
    last = retention.discover_policies(
        admin,
        RetentionPolicyDiscoveryRequest(
            artifact=evaluation.artifact, limit=1, after_resource_id=first["next_cursor"]
        ),
    )
    assert len(last["items"]) == 1
    assert last["next_cursor"] is None

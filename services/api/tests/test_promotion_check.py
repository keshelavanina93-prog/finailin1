"""Retained, isolated-tenant proof of advisory promotion checks and atomic revalidation."""

import os
from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_promotion_check_preserves_state_and_detects_competing_change() -> None:
    proposer = Principal(
        actor_id="synthetic-promotion-proposer",
        display_name="Synthetic eligibility proposer",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="isolated", period="2026-08", currency="GEL"
        ),
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    reviewer = proposer.model_copy(update={"actor_id": "synthetic-promotion-reviewer"})
    definition = ResourceMutation(
        object_type="SemanticContract",
        identity_key="SyntheticEligibility",
        display_name="Synthetic meaning",
        attributes={"kind": "identifier"},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )

    def proposal(item: ResourceMutation) -> ResourceProposal:
        return ResourceProposal(
            title="SYNTHETIC promotion check",
            rationale="Isolated read-only eligibility proof",
            access_entity="__PLATFORM__",
            mutations=[item],
        )

    decision = ResourceReview(decision="APPROVED", rationale="Independent isolated acceptance")
    base = proposal(definition)
    resources.propose(proposer, base)
    assert resources.promotion_check(proposer, base.proposal_id)["status"] == "BLOCKED"
    assert resources.promotion_check(reviewer, base.proposal_id)["status"] == "ELIGIBLE"
    assert resources.proposal_detail(reviewer, base.proposal_id).decision is None
    assert len(resources.proposals(reviewer)) == 1
    resources.review(reviewer, base.proposal_id, decision)
    assert resources.promotion_check(reviewer, base.proposal_id)["status"] == "DECIDED"
    assert len(resources.get_resource(reviewer, definition.resource_id)["versions"]) == 1
    update = definition.model_copy(
        update={
            "expected_version_id": uuid5(base.proposal_id, str(definition.resource_id)),
            "display_name": "Updated synthetic meaning",
        }
    )
    pending = proposal(update)
    competing = proposal(update.model_copy(update={"display_name": "Competing synthetic meaning"}))
    resources.propose(proposer, pending)
    resources.propose(proposer, competing)
    retained_diff = resources.proposal_detail(reviewer, pending.proposal_id).validation["impact"][
        0
    ]["semantic_diff"]
    assert retained_diff["base_version_id"] == str(update.expected_version_id)
    assert retained_diff["changes"] == [
        {
            "path": "/display_name",
            "category": "PRESENTATION",
            "operation": "CHANGE",
            "before": {"present": True, "value": "Synthetic meaning"},
            "after": {"present": True, "value": "Updated synthetic meaning"},
        }
    ]
    # Reading a retained proposal opens a new database connection. Accepted state is untouched.
    assert resources.get_resource(reviewer, definition.resource_id)["resource"]["display_name"] == (
        "Synthetic meaning"
    )
    assert resources.promotion_check(reviewer, pending.proposal_id)["status"] == "ELIGIBLE"
    resources.review(reviewer, competing.proposal_id, decision)
    assert (
        resources.proposal_detail(reviewer, pending.proposal_id).validation["impact"][0][
            "semantic_diff"
        ]
        == retained_diff
    )
    check = resources.promotion_check(reviewer, pending.proposal_id)
    assert check["status"] == "BLOCKED"
    assert "accepted version changed" in check["blockers"][0]
    with pytest.raises(WorkspaceError) as stale:
        resources.review(reviewer, pending.proposal_id, decision)
    assert stale.value.status == 409
    assert resources.proposal_detail(reviewer, pending.proposal_id).decision is None
    assert len(resources.get_resource(reviewer, definition.resource_id)["versions"]) == 2
    outsider = reviewer.model_copy(
        update={"scope": reviewer.scope.model_copy(update={"tenant_id": uuid4()})}
    )
    with pytest.raises(WorkspaceError) as denied:
        resources.promotion_check(outsider, pending.proposal_id)
    assert denied.value.status == 404
    reader = reviewer.model_copy(update={"permissions": ("ontology_read",)})
    assert resources.promotion_check(reader, pending.proposal_id)["status"] == "BLOCKED"

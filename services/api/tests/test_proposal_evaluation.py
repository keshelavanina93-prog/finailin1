import os
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from finai_api.domain.authority import ExactScope, canonical_sha256
from finai_api.domain.resources import (
    ProposalExpectation,
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.proposal_evaluation import record_evaluation, require_evaluation
from finai_api.services.workspace import WorkspaceError


def test_evaluation_cannot_be_reused_for_changed_proposal_or_dependencies():
    proposal = ResourceProposal(
        title="Evidence binding",
        rationale="Verify immutable evaluation binding",
        access_entity="entity",
        mutations=[
            ResourceMutation(
                object_type="LegalEntity",
                identity_key="test",
                display_name="Test",
                attributes={},
                valid_from=datetime.now(UTC),
            )
        ],
    )
    retained = {
        "dependency_heads": {},
        "dependencies": {},
        "schema_versions": {},
        "downstream_impact": {"fingerprint": "abc"},
        "compatibility": "PASS",
        "identity_cycles": "NONE",
    }
    retained["evaluation"] = record_evaluation(proposal, retained)
    require_evaluation(proposal, retained)
    for field, value in [("dependency_heads", {"resource": "changed"}), ("evaluation", {})]:
        changed = deepcopy(retained)
        changed[field] = value
        with pytest.raises(WorkspaceError, match="evaluation evidence"):
            require_evaluation(proposal, changed)
    with pytest.raises(WorkspaceError, match="evaluation evidence"):
        require_evaluation(proposal.model_copy(update={"title": "Changed proposal"}), retained)


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_database_rejects_missing_evidence_and_retains_evidence_after_promotion():
    operator = Principal(
        actor_id="evaluation-author",
        display_name="Synthetic evaluator",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="eval-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review", "ontology_admin"),
    )
    reviewer = operator.model_copy(update={"actor_id": "evaluation-reviewer"})
    proposal = ResourceProposal(
        title="Retained structural evidence",
        rationale="Synthetic persistence acceptance",
        access_entity="__PLATFORM__",
        mutations=[
            ResourceMutation(
                object_type="SemanticContract",
                identity_key="eval:" + uuid4().hex,
                display_name="Evaluation meaning",
                attributes={"kind": "identifier"},
                valid_from=datetime.now(UTC),
            )
        ],
    )
    failed = proposal.model_copy(
        update={
            "proposal_id": uuid4(),
            "expectations": [
                ProposalExpectation(
                    name="Meaning remains monetary",
                    resource_id=proposal.mutations[0].resource_id,
                    attribute_path=["kind"],
                    expected="money",
                )
            ],
        }
    )
    failed_detail = resources.propose(operator, failed)
    assert failed_detail.validation["evaluation"]["status"] == "FAIL"
    assert resources.promotion_check(reviewer, failed.proposal_id)["status"] == "BLOCKED"
    with pytest.raises(WorkspaceError, match="expectations failed"):
        resources.review(
            reviewer,
            failed.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Cannot override failed expectation"),
        )
    assert resources.proposal_detail(reviewer, failed.proposal_id).decision is None
    proposal = proposal.model_copy(
        update={
            "expectations": [
                ProposalExpectation(
                    name="Meaning remains an identifier",
                    resource_id=proposal.mutations[0].resource_id,
                    attribute_path=["kind"],
                    expected="identifier",
                )
            ]
        }
    )
    detail = resources.propose(operator, proposal)
    evidence = detail.validation["evaluation"]
    assert evidence["proposal_hash"] == canonical_sha256(proposal)
    assert resources.promotion_check(reviewer, proposal.proposal_id)["status"] == "ELIGIBLE"
    legacy = proposal.model_copy(update={"proposal_id": uuid4()})
    validation = dict(detail.validation)
    validation.pop("evaluation")
    with resources.resource_connection(operator) as conn:
        conn.execute(
            "INSERT INTO resource_proposals (tenant_id,proposal_id,access_entity,submitted_by,"
            "title,rationale,request_hash,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                operator.scope.tenant_id,
                legacy.proposal_id,
                legacy.access_entity,
                operator.actor_id,
                legacy.title,
                legacy.rationale,
                canonical_sha256(legacy),
                Jsonb({"request": legacy.model_dump(mode="json"), "validation": validation}),
            ),
        )
    assert resources.promotion_check(reviewer, legacy.proposal_id)["status"] == "BLOCKED"
    with (
        pytest.raises(psycopg.errors.RaiseException, match="evaluation"),
        resources.resource_connection(reviewer) as conn,
    ):
        conn.execute(
            "INSERT INTO resource_decisions (tenant_id,proposal_id,access_entity,"
            "decision,reviewed_by,rationale) VALUES (%s,%s,%s,'APPROVED',%s,%s)",
            (
                operator.scope.tenant_id,
                legacy.proposal_id,
                legacy.access_entity,
                reviewer.actor_id,
                "Attempted direct approval without retained evidence",
            ),
        )
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent structural acceptance"),
    )
    assert (
        resources.proposal_detail(reviewer, proposal.proposal_id).validation["evaluation"]
        == evidence
    )
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        resources.resource_connection(reviewer) as conn,
    ):
        conn.execute(
            "UPDATE resource_proposals SET payload='{}'::jsonb "
            "WHERE tenant_id=%s AND proposal_id=%s",
            (operator.scope.tenant_id, proposal.proposal_id),
        )

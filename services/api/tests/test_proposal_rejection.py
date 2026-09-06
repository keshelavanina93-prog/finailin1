"""A blocked change can be explicitly rejected without publishing any proposed truth."""

import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.resources import (
    ProposalExpectation,
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services import resources


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_http_rejects_blocked_proposal_once_without_changing_accepted_truth(monkeypatch):
    operator = Principal(
        actor_id="synthetic-rejection-proposer",
        display_name="Synthetic rejection proposer",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-rejection-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review", "ontology_admin"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-rejection-reviewer"})
    company = ResourceMutation(
        object_type="LegalEntity",
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC unchanged accepted company",
        attributes={"jurisdiction": "SYNTHETIC_ACCEPTED"},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )
    initial = ResourceProposal(
        title="SYNTHETIC accepted company for rejection test",
        rationale="Retain an isolated target before testing immutable rejection",
        access_entity=operator.scope.legal_entity_id,
        mutations=[company],
    )
    resources.propose(operator, initial)
    resources.review(
        reviewer,
        initial.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Retain synthetic accepted target for rejection test",
        ),
    )
    before = resources.get_resource(operator, company.resource_id)
    changed = company.model_copy(
        update={
            "expected_version_id": UUID(before["resource"]["version_id"]),
            "attributes": {"jurisdiction": "SYNTHETIC_PROPOSED"},
        }
    )
    pending = ResourceProposal(
        title="SYNTHETIC blocked company change",
        rationale="This deterministic expectation intentionally fails for rejection acceptance",
        access_entity=operator.scope.legal_entity_id,
        mutations=[changed],
        expectations=[
            ProposalExpectation(
                name="Company jurisdiction must satisfy reviewed contract",
                resource_id=company.resource_id,
                attribute_path=["jurisdiction"],
                expected="SYNTHETIC_REQUIRED",
            )
        ],
    )
    proposed = resources.propose(operator, pending)
    assert proposed.validation["evaluation"]["status"] == "FAIL"
    assert resources.promotion_check(reviewer, pending.proposal_id)["status"] == "BLOCKED"
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "synthetic-rejection-token": reviewer.model_dump(mode="json"),
            }
        ),
    )
    get_settings.cache_clear()
    client = TestClient(app)
    headers = {"Authorization": "Bearer synthetic-rejection-token"}
    path = f"/v1/ontology/proposals/{pending.proposal_id}/decision"
    decision = {
        "decision": "REJECTED",
        "rationale": "Reject the synthetic change because its retained expectation failed",
    }
    try:
        assert client.post(path, json=decision).status_code == 401
        response = client.post(path, json=decision, headers=headers)
        assert response.status_code == 200, response.text
        recorded = response.json()
        assert recorded["decision"] == "REJECTED"
        assert recorded["reviewed_by"] == reviewer.actor_id
        assert recorded["review_rationale"] == decision["rationale"]
        assert recorded["recorded_at"]
        assert recorded["validation"]["evaluation"]["status"] == "FAIL"
        repeated = client.post(path, json=decision, headers=headers)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == recorded
        for conflicting in (
            {**decision, "decision": "APPROVED"},
            {
                **decision,
                "rationale": "Changed synthetic reason cannot overwrite recorded rejection",
            },
        ):
            refused = client.post(path, json=conflicting, headers=headers)
            assert refused.status_code == 409, refused.text
        detail = client.get(f"/v1/ontology/proposals/{pending.proposal_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json() == recorded
        after = resources.get_resource(operator, company.resource_id)
        assert after["resource"] == before["resource"]
        assert after["versions"] == before["versions"]
    finally:
        client.close()
        get_settings.cache_clear()

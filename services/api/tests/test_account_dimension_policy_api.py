"""Real reviewed wrapper lifecycle in an isolated synthetic accounting scope."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, retained  # noqa: F401
from test_journal_dimensions import dimension_case

from finai_api.api.account_dimension_policy_routes import current, propose
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceReview
from finai_api.services import resources
from finai_api.services.account_dimension_policy import ProposalRequest
from finai_api.services.workspace import WorkspaceError


@DB
def test_reviewed_policy_wrapper_replay_and_effective_rule_discovery(retained):
    reader, publish, resource, company, _chart, account, _ = dimension_case(retained)
    author = reader.model_copy(update={"permissions": ("ontology_read", "ontology_propose")})
    reviewer = reader.model_copy(
        update={
            "actor_id": "synthetic-policy-checker",
            "permissions": ("ontology_read", "ontology_review"),
        }
    )
    before = current(reader, company.resource_id, account.resource_id)
    assert before["state"] == "UNESTABLISHED" and before["rules_complete"]
    assert before["rules"] == [] and before["current_use_authorized"] is False

    def pin(node):
        return {key: node[key] for key in ("resource_id", "version_id")}

    request = ProposalRequest(
        request_id=uuid4(),
        expected_version_id=None,
        company=pin(before["company"]),
        chart=pin(before["chart"]),
        account=pin(before["account"]),
        rules=[],
        reason="Synthetic explicit empty analytical policy review",
    )
    pending = propose(author, request)
    assert pending["decision"] is None and pending["review_required"]
    assert propose(author, request) == pending
    resources.review(
        reviewer,
        UUID(pending["proposal_id"]),
        ResourceReview(
            decision="APPROVED", rationale="Independent synthetic explicit empty-set approval"
        ),
    )
    accepted = propose(author, request)
    assert accepted["decision"] == "APPROVED" and not accepted["review_required"]
    assert accepted["proposal_id"] == pending["proposal_id"]
    assert current(reader, company.resource_id, account.resource_id)["state"] == "CURRENT"
    with pytest.raises(WorkspaceError) as changed:
        propose(author, request.model_copy(update={"reason": "Different synthetic policy reason"}))
    assert changed.value.status == 409
    other_company = resource("LegalEntity", {})
    publish(other_company)
    with pytest.raises(WorkspaceError):
        current(reader, other_company.resource_id, account.resource_id)

    dimension = resource("DimensionDefinition", {"code": "SYNTHETIC_" + uuid4().hex})
    publish(dimension)
    key = f"account-dimension:{account.resource_id}:{dimension.resource_id}"
    rule = resource(
        "AccountDimensionRule",
        {
            "account_id": str(account.resource_id),
            "dimension_id": str(dimension.resource_id),
            "required": True,
        },
        resource_id=canonical_id(reader.scope.tenant_id, "AccountDimensionRule", key),
    ).model_copy(update={"identity_key": key})
    saved = publish(rule)[0]
    stale = current(reader, company.resource_id, account.resource_id)
    assert stale["state"] == "STALE" and stale["rules_complete"]
    assert stale["rules"][0]["rule"]["version_id"] == saved["version_id"]
    publish(
        rule.model_copy(
            update={
                "expected_version_id": UUID(saved["version_id"]),
                "valid_from": datetime.now(UTC) + timedelta(days=30),
                "attributes": {**rule.attributes, "required": False},
            }
        )
    )
    scheduled = current(reader, company.resource_id, account.resource_id)
    assert scheduled["rules_complete"] and scheduled["state"] == "STALE"
    assert scheduled["rules"][0]["rule"]["version_id"] == saved["version_id"]
    # Immutable replay stays approved even when the current complete set has changed.
    assert propose(author, request) == accepted

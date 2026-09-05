"""Opt-in native PostgreSQL acceptance for independent effective/knowledge time."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.resources import (
    CanonicalResource,
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

pytestmark = pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained DB acceptance"
)


@pytest.fixture
def operators() -> tuple[Principal, Principal]:
    proposer = Principal(
        actor_id="synthetic-history-proposer",
        display_name="Synthetic history proposer",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-history-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    return proposer, proposer.model_copy(update={"actor_id": "synthetic-history-reviewer"})


def accept(operators: tuple[Principal, Principal], mutation: ResourceMutation) -> CanonicalResource:
    proposer, reviewer = operators
    proposal = ResourceProposal(
        title="SYNTHETIC historical identity acceptance",
        rationale="Isolated non-authentic effective and knowledge time acceptance",
        access_entity=proposer.scope.legal_entity_id,
        mutations=[mutation],
    )
    resources.propose(proposer, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Independent synthetic historical identity review"
        ),
    )
    return CanonicalResource.model_validate(
        resources.get_resource(proposer, mutation.resource_id)["resource"]
    )


def entity(name: str) -> ResourceMutation:
    identifier = uuid4()
    return ResourceMutation(
        resource_id=identifier,
        object_type="LegalEntity",
        identity_key="synthetic:" + str(identifier),
        display_name="SYNTHETIC " + name,
        attributes={},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )


def test_same_effective_date_returns_versions_known_before_and_after_correction(
    operators: tuple[Principal, Principal],
) -> None:
    initial = entity("original recorded company name")
    first = accept(operators, initial)
    corrected = initial.model_copy(
        update={
            "expected_version_id": first.version_id,
            "display_name": "SYNTHETIC corrected company name",
            "valid_from": datetime(2025, 12, 1, tzinfo=UTC),
        }
    )
    second = accept(operators, corrected)
    assert first.system_from < second.system_from
    effective = datetime(2026, 7, 15, tzinfo=UTC)
    before = resources.resolve_identity(
        operators[0], first.resource_id, known_at=first.system_from, valid_at=effective
    )
    after = resources.resolve_identity(
        operators[0], first.resource_id, known_at=second.system_from, valid_at=effective
    )
    assert before["version_id"] == str(first.version_id)
    assert before["display_name"] == first.display_name
    assert after["version_id"] == str(second.version_id)
    assert after["display_name"] == second.display_name
    assert before["valid_at"] == after["valid_at"] == effective
    assert before["known_at"] == first.system_from
    assert after["known_at"] == second.system_from
    # The backdated correction cannot appear before it was recorded.
    backdated = datetime(2025, 12, 15, tzinfo=UTC)
    with pytest.raises(WorkspaceError) as absent:
        resources.resolve_identity(
            operators[0], first.resource_id, known_at=first.system_from, valid_at=backdated
        )
    assert absent.value.status == 404
    assert resources.resolve_identity(
        operators[0], first.resource_id, known_at=second.system_from, valid_at=backdated
    )["version_id"] == str(second.version_id)
    with pytest.raises(WorkspaceError) as unrecorded:
        resources.resolve_identity(
            operators[0],
            first.resource_id,
            known_at=first.system_from - timedelta(microseconds=1),
            valid_at=effective,
        )
    assert unrecorded.value.status == 404


def test_redirect_and_reviewed_split_keep_effective_and_recorded_history(
    operators: tuple[Principal, Principal],
) -> None:
    source = accept(operators, entity("source identity"))
    target = accept(operators, entity("surviving identity"))
    merge = ResourceMutation(
        object_type="IdentityResolution",
        identity_key="identity:" + str(source.resource_id),
        display_name="SYNTHETIC identity merge",
        attributes={
            "source_id": str(source.resource_id),
            "target_id": str(target.resource_id),
            "active": True,
            "survivorship": "Synthetic independent resolution acceptance",
        },
        valid_from=datetime(2026, 7, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )
    merged = accept(operators, merge)
    split = merge.model_copy(
        update={
            "expected_version_id": merged.version_id,
            "display_name": "SYNTHETIC reviewed split",
            "valid_from": datetime(2026, 8, 1, tzinfo=UTC),
            "attributes": {**merge.attributes, "active": False},
        }
    )
    separated = accept(operators, split)
    assert merged.system_from < separated.system_from
    july = datetime(2026, 7, 15, tzinfo=UTC)
    august = datetime(2026, 8, 15, tzinfo=UTC)
    historical_merge = resources.resolve_identity(
        operators[0], source.resource_id, known_at=merged.system_from, valid_at=august
    )
    effective_merge = resources.resolve_identity(
        operators[0], source.resource_id, known_at=separated.system_from, valid_at=july
    )
    current_split = resources.resolve_identity(
        operators[0], source.resource_id, known_at=separated.system_from, valid_at=august
    )
    for result in (historical_merge, effective_merge):
        assert result["canonical_id"] == str(target.resource_id)
        assert result["version_id"] == str(target.version_id)
        assert result["resolution_chain"] == [str(source.resource_id), str(target.resource_id)]
    assert current_split["canonical_id"] == str(source.resource_id)
    assert current_split["version_id"] == str(source.version_id)
    assert current_split["resolution_chain"] == [str(source.resource_id)]
    assert resources.resolve_identity(
        operators[0], source.resource_id, known_at=target.system_from, valid_at=august
    )["canonical_id"] == str(source.resource_id)

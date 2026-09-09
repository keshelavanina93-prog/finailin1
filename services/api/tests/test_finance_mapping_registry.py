"""Local-to-global mapping registry remains a pinned candidate until review."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.finance_mapping_registry import MappingRegistryEntry
from finai_api.domain.review import Principal
from finai_api.services.finance_mapping_registry import (
    mapping_registry_proposal_id,
    prepare_mapping_registry_proposal,
    registry_manifest,
)
from finai_api.services.workspace import WorkspaceError

AT = datetime(2025, 1, 1, tzinfo=UTC)


@pytest.fixture
def principal() -> Principal:
    return Principal(
        actor_id="mapping-maker",
        display_name="Mapping maker",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="sgp-entity",
            period="2025-01",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose"),
    )


@pytest.fixture
def entry() -> MappingRegistryEntry:
    local, group, evidence, record = uuid4(), uuid4(), uuid4(), uuid4()
    return MappingRegistryEntry(
        local_account_id=local,
        local_account_version_id=uuid4(),
        global_account_id=group,
        global_account_version_id=uuid4(),
        projection_code="STATUTORY_IS",
        source_record_ids=[record],
        source_record_version_ids={record: uuid4()},
        evidence_id=evidence,
        evidence_version_id=uuid4(),
        local_account_code="6110",
    )


def test_registry_is_versioned_and_proposal_is_retry_stable(principal, entry):
    manifest = registry_manifest(
        registry_id="g8.finance.ifrs",
        registry_version=3,
        source_family="1C_ACCOUNT_PERIOD",
        source_hashes=["b" * 64, "a" * 64],
        entries=[entry],
    )
    assert manifest.status == "PROPOSED"
    assert manifest.authority == "CANDIDATE_ONLY"
    assert manifest.source_hashes == ["a" * 64, "b" * 64]
    first = prepare_mapping_registry_proposal(
        principal,
        registry_id="g8.finance.ifrs",
        registry_version=3,
        source_family="1C_ACCOUNT_PERIOD",
        source_hashes=["b" * 64, "a" * 64],
        entries=[entry],
        rationale="Review exact local account to global taxonomy binding",
        valid_from=AT,
    )
    second = prepare_mapping_registry_proposal(
        principal,
        registry_id="g8.finance.ifrs",
        registry_version=3,
        source_family="1C_ACCOUNT_PERIOD",
        source_hashes=["a" * 64, "b" * 64],
        entries=[entry],
        rationale="A different explanation does not change the semantic effect",
        valid_from=AT,
    )
    assert first.proposal_id == second.proposal_id
    assert first.mutations[0].object_type == "AccountMappingVersion"
    assert first.mutations[0].attributes["local_account_id"] == str(entry.local_account_id)
    assert first.mutations[0].attributes["group_account_id"] == str(entry.global_account_id)
    assert first.mutations[0].attributes["evidence_id"] == str(entry.evidence_id)
    assert first.source_versions[first.mutations[0].resource_id][entry.local_account_id] == (
        entry.local_account_version_id
    )
    assert first.source_versions[first.mutations[0].resource_id][entry.global_account_id] == (
        entry.global_account_version_id
    )


def test_registry_rejects_duplicate_local_projection_and_unpinned_source_record(principal, entry):
    with pytest.raises(WorkspaceError, match="duplicate local-account"):
        registry_manifest(
            registry_id="g8.finance.ifrs",
            registry_version=1,
            source_family="1C_ACCOUNT_PERIOD",
            source_hashes=["a" * 64],
            entries=[entry, entry],
        )
    unpinned = entry.model_copy(update={"source_record_version_ids": {}})
    with pytest.raises(WorkspaceError, match="exact reviewed version pin"):
        registry_manifest(
            registry_id="g8.finance.ifrs",
            registry_version=1,
            source_family="1C_ACCOUNT_PERIOD",
            source_hashes=["a" * 64],
            entries=[unpinned],
        )


def test_registry_different_version_has_different_identity(principal, entry):
    first = prepare_mapping_registry_proposal(
        principal,
        registry_id="g8.finance.ifrs",
        registry_version=1,
        source_family="1C_ACCOUNT_PERIOD",
        source_hashes=["a" * 64],
        entries=[entry],
        rationale="Review first version of the mapping registry",
        valid_from=AT,
    )
    second = prepare_mapping_registry_proposal(
        principal,
        registry_id="g8.finance.ifrs",
        registry_version=2,
        source_family="1C_ACCOUNT_PERIOD",
        source_hashes=["a" * 64],
        entries=[entry],
        rationale="Review successor version of the mapping registry",
        valid_from=AT,
    )
    assert first.proposal_id != second.proposal_id
    assert (
        mapping_registry_proposal_id(
            principal,
            registry_manifest(
                registry_id="g8.finance.ifrs",
                registry_version=1,
                source_family="1C_ACCOUNT_PERIOD",
                source_hashes=["a" * 64],
                entries=[entry],
            ),
        )
        == first.proposal_id
    )

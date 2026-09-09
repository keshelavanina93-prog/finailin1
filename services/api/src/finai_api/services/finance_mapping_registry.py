"""Prepare governed local-account to global-taxonomy mapping proposals."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid5

from finai_api.domain.finance_mapping_registry import MappingRegistry, MappingRegistryEntry
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

SOURCE_HASH = r"^[a-f0-9]{64}$"
MAPPING_TYPE = "AccountMappingVersion"


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _hashes(source_hashes: Sequence[str]) -> list[str]:
    values = sorted(set(source_hashes))
    if not values or any(
        len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        for value in values
    ):
        raise WorkspaceError(422, "Mapping registry requires lowercase source SHA-256 hashes")
    return values


def registry_manifest(
    *,
    registry_id: str,
    registry_version: int,
    source_family: str,
    source_hashes: Sequence[str],
    entries: Sequence[MappingRegistryEntry],
) -> MappingRegistry:
    """Validate and freeze a registry manifest without touching the database."""

    if not source_family.strip():
        raise WorkspaceError(422, "Mapping registry requires a source family")
    unique = {(entry.local_account_id, entry.projection_code) for entry in entries}
    if len(unique) != len(entries):
        raise WorkspaceError(
            422, "A mapping registry cannot contain duplicate local-account projections"
        )
    if any(len(set(entry.source_record_ids)) != len(entry.source_record_ids) for entry in entries):
        raise WorkspaceError(422, "Mapping registry source records must be unique per entry")
    for entry in entries:
        if set(entry.source_record_ids) != set(entry.source_record_version_ids):
            raise WorkspaceError(422, "Every source record must have an exact reviewed version pin")
    return MappingRegistry(
        registry_id=registry_id,
        registry_version=registry_version,
        source_family=source_family,
        source_hashes=_hashes(source_hashes),
        entries=list(entries),
    )


def mapping_registry_proposal_id(principal: Principal, manifest: MappingRegistry) -> UUID:
    """Derive one retry-stable proposal UUID from scope and frozen evidence."""

    digest = _digest(
        {
            "scope": principal.scope.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
        }
    )
    return uuid5(principal.scope.tenant_id, "finance-mapping-registry:" + digest)


def prepare_mapping_registry_proposal(
    principal: Principal,
    *,
    registry_id: str,
    registry_version: int,
    source_family: str,
    source_hashes: Sequence[str],
    entries: Sequence[MappingRegistryEntry],
    rationale: str,
    valid_from: datetime | None = None,
) -> ResourceProposal:
    """Build a source-bound candidate proposal for independent review.

    Local account versions, global group account versions, source records and
    retained SourceEvidence are all exact dependencies.  This function does
    not look up, approve, or publish any of them.
    """

    if len(rationale.strip()) < 10:
        raise WorkspaceError(422, "Mapping registry rationale needs ten non-padding characters")
    effective = valid_from or datetime.now(UTC)
    if effective.tzinfo is None or effective.utcoffset() is None:
        raise WorkspaceError(422, "Mapping registry effective time requires an explicit timezone")
    manifest = registry_manifest(
        registry_id=registry_id,
        registry_version=registry_version,
        source_family=source_family,
        source_hashes=source_hashes,
        entries=entries,
    )
    proposal_id = mapping_registry_proposal_id(principal, manifest)
    mutations: list[ResourceMutation] = []
    source_versions: dict[UUID, dict[UUID, UUID]] = {}
    for entry in manifest.entries:
        identity_key = (
            f"{manifest.registry_id}:{manifest.registry_version}:"
            f"{entry.local_account_id}:{entry.projection_code}"
        )
        resource_id = uuid5(proposal_id, "mapping:" + identity_key)
        mutations.append(
            ResourceMutation(
                resource_id=resource_id,
                object_type=MAPPING_TYPE,
                identity_key=identity_key,
                display_name=f"{entry.local_account_code} · {entry.projection_code}",
                valid_from=effective,
                evidence_class="SOURCE_BOUND",
                attributes={
                    "local_account_id": str(entry.local_account_id),
                    "group_account_id": str(entry.global_account_id),
                    "projection_code": entry.projection_code,
                    "source_record_ids": [str(item) for item in entry.source_record_ids],
                    "evidence_id": str(entry.evidence_id),
                },
            )
        )
        source_versions[resource_id] = {
            entry.local_account_id: entry.local_account_version_id,
            entry.global_account_id: entry.global_account_version_id,
            entry.evidence_id: entry.evidence_version_id,
            **entry.source_record_version_ids,
        }
    return ResourceProposal(
        proposal_id=proposal_id,
        title=f"Review {manifest.registry_id} v{manifest.registry_version} account mappings",
        rationale=(
            rationale.strip()
            + " Local and global taxonomies remain separate; publication requires independent "
            "review and exact retained source pins."
        ),
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
        source_versions=source_versions,
    )


def submit_mapping_registry_proposal(principal: Principal, proposal: ResourceProposal) -> Any:
    """Submit a prepared registry through the existing governed queue."""

    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    return resources.propose(principal, proposal)


prepare_account_mapping_proposal = prepare_mapping_registry_proposal
submit_account_mapping_proposal = submit_mapping_registry_proposal

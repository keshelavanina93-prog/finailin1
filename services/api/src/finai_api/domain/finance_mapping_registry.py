"""Versioned local-to-global finance mapping registry contracts.

The local account and global group account are separate canonical resources.
This module only prepares a source-bound ``AccountMappingVersion`` proposal;
the normal resource proposal and independent review path remains the authority
that can publish it.  A registry/version is encoded into the identity key so a
new mapping registry never silently mutates an older semantic interpretation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MappingRegistryEntry(BaseModel):
    """One exact local-account to global-group candidate binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    local_account_id: UUID
    local_account_version_id: UUID
    global_account_id: UUID
    global_account_version_id: UUID
    projection_code: Literal[
        "CORPORATE_MR",
        "PETROLEUM_OPERATING_PL",
        "GAS_GROUP_PL",
        "STATUTORY_BS",
        "STATUTORY_IS",
        "GAS_CF",
    ]
    source_record_ids: list[UUID] = Field(min_length=1, max_length=100)
    source_record_version_ids: dict[UUID, UUID] = Field(min_length=1, max_length=100)
    evidence_id: UUID
    evidence_version_id: UUID
    local_account_code: str = Field(min_length=1, max_length=128)


class MappingRegistry(BaseModel):
    """Deterministic registry manifest retained inside a proposal request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["finance-mapping-registry/1"] = "finance-mapping-registry/1"
    registry_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,120}$")
    registry_version: int = Field(ge=1, le=10000)
    source_family: str = Field(min_length=1, max_length=128)
    source_hashes: list[str] = Field(min_length=1, max_length=100)
    status: Literal["PROPOSED"] = "PROPOSED"
    authority: Literal["CANDIDATE_ONLY"] = "CANDIDATE_ONLY"
    entries: list[MappingRegistryEntry] = Field(min_length=1, max_length=100)


class MappingRegistryProposalRequest(BaseModel):
    """HTTP request for one deterministic, review-only registry proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,120}$")
    registry_version: int = Field(ge=1, le=10000)
    source_family: str = Field(min_length=1, max_length=128)
    source_hashes: list[str] = Field(min_length=1, max_length=100)
    entries: list[MappingRegistryEntry] = Field(min_length=1, max_length=100)
    valid_from: datetime
    rationale: str = Field(min_length=10, max_length=2000)

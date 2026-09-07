"""Content identity for retained build bytes; no build or release attestation."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArtifactDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["retained-build-artifact/1"]
    authority: Literal["RETAINED_BYTES_ONLY"]
    artifact_kind: Literal["SOURCE_ARCHIVE", "API_WHEEL", "WEB_STANDALONE"]


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_length: int = Field(strict=True, ge=1, le=32_000_000)
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")
    evidence_id: UUID
    definition: ArtifactDefinition

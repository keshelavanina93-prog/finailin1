"""Explicit source and canonical version selections for finance candidate review."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConstructionId = Literal["g8.candidate.coa-406", "g8.candidate.seg-entities"]


class CandidateVersionPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID
    version_id: UUID


class CandidateIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    construction_id: ConstructionId
    document_id: str | None = Field(default=None, min_length=1, max_length=256)
    evidence: CandidateVersionPin | None = None
    company: CandidateVersionPin | None = None
    chart: CandidateVersionPin | None = None
    valid_from: datetime
    offset: int = Field(default=0, ge=0)
    # Each account needs four native mutations, including retained source lineage.
    limit: int = Field(default=25, ge=1, le=25)
    rationale: str = Field(min_length=10, max_length=1500)

    @field_validator("valid_from")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Candidate effective time requires an explicit timezone")
        return value

    @field_validator("rationale")
    @classmethod
    def meaningful_rationale(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Candidate rationale needs ten non-padding characters")
        return value.strip()

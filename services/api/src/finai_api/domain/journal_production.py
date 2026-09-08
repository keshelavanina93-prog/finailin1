"""Bounded operator intent; amounts and accounts always come from retained source."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finai_api.domain.journal_dimensions import LineDimensions
from finai_api.domain.resource_lifecycle import VersionReference


class SidePolicies(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    debit: LineDimensions
    credit: LineDimensions
    source_record: VersionReference | None = None


class JournalProductionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    invocation_id: UUID
    company_id: UUID
    effective_at: datetime
    rationale: str = Field(min_length=10, max_length=2000)
    # Explicit bounded selection for submission; preview still reports every row.
    coordinates: list[str] = Field(default_factory=list, max_length=20)
    policies: dict[str, SidePolicies] = Field(default_factory=dict, max_length=20)

    @field_validator("effective_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Journal effective time must include a timezone")
        return value

    @field_validator("coordinates")
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Source row selection must be distinct")
        return value

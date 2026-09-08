"""Explicit retained-evidence Action requests; never caller-authored finding facts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InvestigationAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    rationale: str = Field(min_length=10, max_length=2000)
    expected_finding_version_id: UUID | None = None
    expected_investigation_version_id: UUID | None = None

    @model_validator(mode="after")
    def paired_heads(self):
        if (self.expected_finding_version_id is None) != (
            self.expected_investigation_version_id is None
        ):
            raise ValueError("Finding and Investigation expected heads must be supplied together")
        return self

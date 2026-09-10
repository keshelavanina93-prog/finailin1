"""Read-only enterprise target diagnosis; selection never grants financial authority."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1, max_length=512)
    company_id: UUID | None = None
    root_version_id: UUID | None = None
    period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    valid_at: datetime | None = None
    known_at: datetime | None = None

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Diagnostic timestamps must include a timezone")
        return value

    @field_validator("target_id")
    @classmethod
    def meaningful_target(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Select an enterprise target or canonical resource")
        return value

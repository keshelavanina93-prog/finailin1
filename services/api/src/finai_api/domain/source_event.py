import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finai_api.domain.resource_lifecycle import VersionReference


class SourceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stream: VersionReference
    event_id: str = Field(min_length=1, max_length=256)
    partition_key: str = Field(min_length=1, max_length=256)
    event_time: datetime
    payload: dict[str, Any]

    @field_validator("event_time")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Event time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded_payload(self) -> "SourceEvent":
        if len(json.dumps(self.payload, allow_nan=False).encode()) > 1_000_000:
            raise ValueError("Event payload exceeds the retained observation limit")
        return self

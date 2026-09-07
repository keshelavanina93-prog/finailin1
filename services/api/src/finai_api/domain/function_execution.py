"""Canonical deterministic Function adapter contracts; no caller-supplied executable code."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finai_api.domain.resource_lifecycle import VersionReference


class FunctionImplementation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    implementation_id: Literal["ontology.object-set-derived/v1"]
    determinism: Literal["DETERMINISTIC_FOR_PINNED_INPUTS"]
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dependency_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    derived_property_ids: list[UUID] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_properties(self) -> "FunctionImplementation":
        if len(set(self.derived_property_ids)) != len(self.derived_property_ids):
            raise ValueError("Function derived property identities must be unique")
        return self


class FunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_set_id: UUID
    definition: FunctionImplementation
    evidence_id: UUID | None = None


class FunctionInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID = Field(default_factory=uuid4)
    function: VersionReference
    valid_at: datetime
    known_at: datetime
    offset: int = Field(default=0, ge=0, le=1000000)
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Function timestamps must include a timezone")
        return value

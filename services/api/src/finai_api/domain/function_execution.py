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


class WorksheetImplementation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    implementation_id: Literal["source.retained-xls-worksheet/v1"]
    determinism: Literal["DETERMINISTIC_FOR_PINNED_INPUTS"]
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dependency_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sheet: str = Field(min_length=1, max_length=128)
    first_row: int = Field(strict=True, ge=0, le=1000000)
    row_count: int = Field(strict=True, ge=1, le=50)

    @property
    def derived_property_ids(self) -> list[UUID]:
        return []


class FunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_set_id: UUID | None = None
    definition: FunctionImplementation | WorksheetImplementation = Field(
        discriminator="implementation_id"
    )
    evidence_id: UUID | None = None

    @model_validator(mode="after")
    def adapter_inputs(self) -> "FunctionDefinition":
        if isinstance(self.definition, WorksheetImplementation):
            if self.evidence_id is None or self.object_set_id is not None:
                raise ValueError("Worksheet Function requires SourceEvidence and no Object Set")
        elif self.object_set_id is None:
            raise ValueError("Ontology Function requires an Object Set")
        return self


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

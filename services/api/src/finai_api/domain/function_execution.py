"""Canonical deterministic Function adapter contracts; no caller-supplied executable code."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finai_api.domain.resource_lifecycle import VersionReference


class GroupCount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_id: UUID
    fields: list[str] = Field(min_length=1, max_length=4)

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(
            not name.strip() or len(name) > 128 for name in value
        ):
            raise ValueError("Grouping fields must be unique bounded canonical property names")
        return value


class TemporalExtent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_id: UUID
    field: str = Field(min_length=1, max_length=128)


class Materialization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_objects: int = Field(strict=True, ge=1, le=1000)
    max_pages: int = Field(strict=True, ge=1, le=10)


class FunctionImplementation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    implementation_id: Literal["ontology.object-set-derived/v1"]
    determinism: Literal["DETERMINISTIC_FOR_PINNED_INPUTS"]
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dependency_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    derived_property_ids: list[UUID] = Field(default_factory=list, max_length=8)
    group_count: GroupCount | None = Field(default=None, exclude_if=lambda value: value is None)
    temporal_extent: TemporalExtent | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    retained_properties: list[VersionReference] = Field(
        default_factory=list, max_length=8, exclude_if=lambda value: not value
    )
    materialization: Materialization | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def unique_properties(self) -> "FunctionImplementation":
        if self.materialization and (self.derived_property_ids or self.retained_properties):
            raise ValueError("Materialization does not support calculated properties")
        if len(set(self.derived_property_ids)) != len(self.derived_property_ids):
            raise ValueError("Function derived property identities must be unique")
        if len({ref.resource_id for ref in self.retained_properties}) != len(
            self.retained_properties
        ):
            raise ValueError("Retained property identities must be unique")
        if self.retained_properties and not self.derived_property_ids:
            raise ValueError("Retained properties require declared derived outputs")
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


class PostedMovementsImplementation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    implementation_id: Literal["accounting.retained-posted-movements/v1"]
    determinism: Literal["DETERMINISTIC_FOR_PINNED_INPUTS"]
    code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dependency_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_id: str = Field(pattern=r"^(doc|ir)_[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sheet: str = Field(min_length=1, max_length=128)
    max_source_rows: int = Field(strict=True, ge=1, le=1000)
    entity_movement_review: bool = Field(
        default=False, strict=True, exclude_if=lambda value: not value
    )
    movement_display_fraction_digits: int | None = Field(
        default=None, strict=True, ge=0, le=6, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def movement_presentation(self):
        if self.movement_display_fraction_digits is not None and not self.entity_movement_review:
            raise ValueError("Movement display precision requires entity movement review")
        return self

    @property
    def derived_property_ids(self) -> list[UUID]:
        return []


class FunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_set_id: UUID | None = None
    definition: FunctionImplementation | WorksheetImplementation | PostedMovementsImplementation = (
        Field(discriminator="implementation_id")
    )
    evidence_id: UUID | None = None
    accounting_binding_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    source_scope_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    minimum_authority_state: Literal["OBSERVED"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def adapter_inputs(self) -> "FunctionDefinition":
        if isinstance(self.definition, PostedMovementsImplementation):
            if (
                self.object_set_id is not None
                or self.evidence_id is None
                or self.accounting_binding_id is None
                or self.source_scope_id is None
                or self.minimum_authority_state is None
            ):
                raise ValueError(
                    "Posted movements require exact source, binding and authority inputs"
                )
        elif any((self.accounting_binding_id, self.source_scope_id, self.minimum_authority_state)):
            raise ValueError("Accounting inputs require the posted movements adapter")
        elif isinstance(self.definition, WorksheetImplementation):
            if self.evidence_id is None or self.object_set_id is not None:
                raise ValueError("Worksheet Function requires SourceEvidence and no Object Set")
        elif self.object_set_id is None:
            raise ValueError("Ontology Function requires an Object Set")
        return self


class RetainedResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: UUID


class FunctionInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID = Field(default_factory=uuid4)
    function: VersionReference
    valid_at: datetime
    known_at: datetime
    offset: int = Field(default=0, ge=0, le=1000000)
    limit: int = Field(default=50, ge=1, le=200)
    input_result: RetainedResultInput | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def complete_input_page(self) -> "FunctionInvocation":
        if self.input_result is not None and self.offset != 0:
            raise ValueError("Retained input consumes the complete page; offset must be zero")
        if self.input_result is not None and self.input_result.invocation_id == self.request_id:
            raise ValueError("Function cannot consume its own result")
        return self

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Function timestamps must include a timezone")
        return value

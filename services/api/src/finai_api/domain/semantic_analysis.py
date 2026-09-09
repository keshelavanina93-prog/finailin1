"""Typed presentation of retained shared results; descriptors grant no new authority."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

Scalar = StrictStr | StrictInt | StrictBool | None


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Pin(Model):
    resource_id: UUID
    version_id: UUID
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Value(Model):
    state: Literal["VALUE", "NULL", "MISSING"] = "VALUE"
    value: Scalar = None
    label: str | None = None
    reference: Pin | None = None


class Filter(Model):
    field: str = Field(min_length=1, max_length=128)
    state: Literal["VALUE", "NULL", "MISSING"] = "VALUE"
    value: Scalar = None


class ProjectionRequest(Model):
    invocation_id: UUID
    company_id: UUID
    descriptor_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    filters: list[Filter] = Field(default_factory=list, max_length=4)
    group_by: str | None = Field(default=None, min_length=1, max_length=128)
    selected_row: str | None = Field(default=None, pattern=r"^row_[a-f0-9]{64}$")
    contributor_index: int = Field(default=0, ge=0, le=999, strict=True)

    @model_validator(mode="after")
    def pinned_operations(self):
        if (self.filters or self.group_by or self.selected_row) and not self.descriptor_sha256:
            raise ValueError("Workspace operations require the exact descriptor revision")
        if len({item.field for item in self.filters}) != len(self.filters):
            raise ValueError("Filter dimensions must be distinct")
        if self.contributor_index and self.selected_row is None:
            raise ValueError("Select a retained group before a contributor")
        return self


class DecimalPresentation(Model):
    format: Literal["FIXED_DECIMAL"]
    fraction_digits: int = Field(strict=True, ge=0, le=6)
    currency: Pin


class FieldDefinition(Model):
    key: str
    label: str
    kind: Literal[
        "text", "identifier", "reference", "integer", "decimal", "boolean", "date", "datetime"
    ]
    role: Literal["DIMENSION", "MEASURE", "ATTRIBUTE"]
    unit: str | None = None
    unit_reference: Pin | None = None
    definition: Pin
    field_id: UUID | None = None
    semantic_id: UUID | None = None
    filterable: bool = False
    groupable: bool = False
    aggregation: Literal["NONE", "RETAINED_VALUE_ONLY"] = "NONE"
    options: list[Value] = Field(default_factory=list, max_length=1000)
    presentation: DecimalPresentation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def presentation_context(self):
        if self.presentation is not None and (
            self.kind != "decimal"
            or self.role not in {"ATTRIBUTE", "MEASURE"}
            or not self.unit
            or not self.unit.strip()
            or self.unit_reference != self.presentation.currency
        ):
            raise ValueError("Decimal presentation requires the field's exact currency context")
        return self


class Row(Model):
    key: str = Field(pattern=r"^row_[a-f0-9]{64}$")
    label: str
    values: dict[str, Value]
    contributor_count: int = Field(ge=0, le=1000)
    trace: Pin


class EvidenceCell(Model):
    label: str
    value: Scalar
    coordinate: str | None = None
    formula: str | None = None


class Contributor(Model):
    label: str
    reference: Pin
    cells: list[EvidenceCell] = Field(default_factory=list, max_length=256)
    document_id: str | None = None
    source_sha256: str | None = None
    sheet: str | None = None
    coordinate: str | None = None
    basis: Literal["ORIGINAL_SOURCE", "CANONICAL_DEFINITION", "UNAVAILABLE"] = Field(
        default="ORIGINAL_SOURCE", exclude_if=lambda value: value == "ORIGINAL_SOURCE"
    )


class Selection(Model):
    row_key: str
    contributor_index: int
    contributor_count: int
    contributor: Contributor


class Section(Model):
    label: str
    row_keys: list[str]


class Coverage(Model):
    label: str
    value: str


class Descriptor(Model):
    contract: Literal["semantic-analysis/1", "semantic-analysis/2"] = "semantic-analysis/1"
    invocation_id: UUID
    receipt_hash: str
    run_id: str
    function: Pin
    company: Pin
    company_label: str
    title: str
    row_noun: Literal["groups", "objects"] = Field(
        default="groups", exclude_if=lambda value: value == "groups"
    )
    grain: list[str]
    partition_keys: list[str] = Field(default_factory=list)
    fields: list[FieldDefinition]
    measure: str | None
    visual: Literal["HORIZONTAL_BARS", "NONE"] = "HORIZONTAL_BARS"
    filtering: Literal["RETAINED_GROUP_SELECTION"] = "RETAINED_GROUP_SELECTION"
    grouping: Literal["RETAINED_ROWS_WITHOUT_AGGREGATION"] = "RETAINED_ROWS_WITHOUT_AGGREGATION"
    authority: str
    coverage: list[Coverage]
    context: list[Coverage] = Field(default_factory=list)
    valid_at: str
    known_at: str
    recorded_at: str
    definitions: list[Pin]
    unavailable_operations: list[str]
    excluded_evidence: list[Contributor] = Field(default_factory=list, max_length=1000)
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False

    @model_validator(mode="after")
    def available_measure(self):
        measures = [field for field in self.fields if field.role == "MEASURE"]
        if self.measure is None:
            if self.contract != "semantic-analysis/2" or self.visual != "NONE" or measures:
                raise ValueError(
                    "Measure-free definitions require an explicit table-only descriptor"
                )
        elif (
            self.visual != "HORIZONTAL_BARS"
            or len(measures) != 1
            or measures[0].key != self.measure
            or measures[0].kind not in {"decimal", "integer"}
        ):
            raise ValueError("A magnitude visual requires one designated numeric measure")
        return self


class Projection(Model):
    descriptor: Descriptor
    descriptor_sha256: str
    rows: list[Row] = Field(max_length=1000)
    total_rows: int = Field(ge=0, le=1000)
    sections: list[Section]
    selection: Selection | None
    request: ProjectionRequest

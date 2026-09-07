"""Portable ontology queries; no SQL or application-specific joins in callers."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class PropertyFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: str = Field(min_length=1, max_length=128)
    value: StrictStr | StrictInt | StrictBool | None
    operator: Literal["eq", "lt", "lte", "gt", "gte"] = Field(
        default="eq", exclude_if=lambda value: value == "eq"
    )


class Traversal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["reference", "link"] = "reference"
    name: str = Field(min_length=1, max_length=128)
    direction: Literal["outgoing", "incoming"] = "outgoing"
    filters: list[PropertyFilter] = Field(
        default_factory=list, max_length=20, exclude_if=lambda value: not value
    )


class InterfacePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID
    version_id: UUID


class InterfaceRoot(InterfacePin):
    implementations: list[InterfacePin] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_implementations(self):
        if len({item.resource_id for item in self.implementations}) != len(self.implementations):
            raise ValueError("Interface implementation identities must be unique")
        return self


class ObjectSetQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    object_type: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{1,63}$")
    resource_ids: list[UUID] | None = Field(default=None, max_length=100)
    filters: list[PropertyFilter] = Field(default_factory=list, max_length=20)
    traversal: list[Traversal] = Field(default_factory=list, max_length=4)
    search: str = Field(default="", max_length=128)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=1000000)
    valid_at: datetime | None = None
    known_at: datetime | None = None
    interface: InterfaceRoot | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def predicate_budget(self):
        if self.interface is not None and self.object_type != "ObjectInterface":
            raise ValueError("A pinned interface root requires object_type ObjectInterface")
        if len(self.filters) + sum(len(step.filters) for step in self.traversal) > 20:
            raise ValueError("Object Set root and traversal filters share a 20-predicate limit")
        return self

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Query timestamps must include a timezone")
        return value


class FilterSchemaVersion(BaseModel):
    object_type: str
    resource_id: UUID
    version_id: UUID


class TraversalSchemaVersion(FilterSchemaVersion):
    step: int = Field(ge=1, le=4)


class ObjectSetResult(BaseModel):
    contract: Literal["ontology-object-set/1"] = "ontology-object-set/1"
    query: ObjectSetQuery
    total: int
    counts_by_type: dict[str, int]
    objects: list[dict[str, Any]]
    next_offset: int | None
    filter_schema_versions: list[FilterSchemaVersion] = Field(default_factory=list)
    traversal_schema_versions: list[TraversalSchemaVersion] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
    interface_bindings: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    interface_values: list[dict[str, Any]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

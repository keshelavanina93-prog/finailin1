"""Portable ontology queries; no SQL or application-specific joins in callers."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
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
    value: (
        StrictStr
        | StrictInt
        | StrictBool
        | Annotated[list[StrictStr | StrictInt | StrictBool], Field(min_length=1, max_length=100)]
        | None
    )
    operator: Literal["eq", "lt", "lte", "gt", "gte", "in", "not_in"] = Field(
        default="eq", exclude_if=lambda value: value == "eq"
    )

    @model_validator(mode="after")
    def membership_values(self):
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 100:
                raise ValueError("Membership requires a list of 1 to 100 scalar values")
            if len({type(value) for value in self.value}) != 1:
                raise ValueError("Membership values must have the same strict scalar type")
            if len({(type(value), value) for value in self.value}) != len(self.value):
                raise ValueError("Membership values must be unique")
        elif isinstance(self.value, list):
            raise ValueError("Scalar filters cannot receive a list")
        return self


class FilterExpression(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["all", "any"]
    conditions: list[PropertyFilter | FilterExpression] = Field(min_length=2, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def bounded_tree(cls, value):
        pending = [(value, 1)]
        leaves = 0
        while pending:
            node, depth = pending.pop()
            group = isinstance(node, cls) or (
                isinstance(node, dict) and ("op" in node or "conditions" in node)
            )
            if group:
                if depth > 3:
                    raise ValueError("Filter expressions support at most three group levels")
                children = node.conditions if isinstance(node, cls) else node.get("conditions")
                if not isinstance(children, list) or not 2 <= len(children) <= 20:
                    raise ValueError("Filter groups require two to twenty conditions")
                pending.extend((child, depth + 1) for child in children)
            else:
                leaves += 1
                if leaves > 20:
                    raise ValueError("Filter expressions share a twenty-predicate limit")
        return value

    def leaves(self) -> list[PropertyFilter]:
        return [
            leaf
            for node in self.conditions
            for leaf in ([node] if isinstance(node, PropertyFilter) else node.leaves())
        ]


class Traversal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["reference", "link"] = "reference"
    name: str = Field(min_length=1, max_length=128)
    direction: Literal["outgoing", "incoming"] = "outgoing"
    filters: list[PropertyFilter] = Field(
        default_factory=list, max_length=20, exclude_if=lambda value: not value
    )
    filter_expression: FilterExpression | None = Field(
        default=None, exclude_if=lambda value: value is None
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
    filter_expression: FilterExpression | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    traversal: list[Traversal] = Field(default_factory=list, max_length=4)
    search: str = Field(default="", max_length=128)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=1000000)
    valid_at: datetime | None = None
    known_at: datetime | None = None
    interface: InterfaceRoot | None = Field(default=None, exclude_if=lambda value: value is None)
    type_group: InterfacePin | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def predicate_budget(self):
        if self.type_group is not None and (
            self.interface is not None or self.object_type != "ObjectTypeGroup"
        ):
            raise ValueError("A pinned type group requires ObjectTypeGroup and excludes interface")
        if self.interface is not None and self.object_type != "ObjectInterface":
            raise ValueError("A pinned interface root requires object_type ObjectInterface")
        conditions = self.filters + [
            condition for step in self.traversal for condition in step.filters
        ]
        for context in [self, *self.traversal]:
            if context.filter_expression:
                conditions += context.filter_expression.leaves()
        if len(conditions) > 20:
            raise ValueError("Object Set root and traversal filters share a 20-predicate limit")
        if sum(len(c.value) for c in conditions if isinstance(c.value, list)) > 100:
            raise ValueError(
                "Object Set root and traversal membership values share a 100-value limit"
            )
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
    type_group_bindings: dict[str, Any] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    type_group_values: list[dict[str, Any]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

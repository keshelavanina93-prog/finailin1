"""Public query response contracts; dynamic business attributes retain their schema authority."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter

from finai_api.domain.object_sets import (
    FilterSchemaVersion,
    InterfacePin,
    ObjectSetQuery,
    TraversalSchemaVersion,
)
from finai_api.domain.resources import CanonicalResource


def _wire_timestamp(value):
    """Validate the instant without rewriting retained fractional precision."""
    TypeAdapter(AwareDatetime).validate_python(value)
    return value.isoformat() if isinstance(value, datetime) else value


WireTimestamp = Annotated[
    str, BeforeValidator(_wire_timestamp), Field(json_schema_extra={"format": "date-time"})
]


class QueryResource(CanonicalResource):
    # Preserve additive provenance supplied by the canonical resource store.
    model_config = ConfigDict(extra="allow")
    # This wire boundary retains strings; the canonical domain uses datetime values.
    valid_from: WireTimestamp  # type: ignore[assignment]
    valid_to: WireTimestamp | None  # type: ignore[assignment]
    system_from: WireTimestamp  # type: ignore[assignment]


class HashedPin(InterfacePin):
    content_hash: str


class SharedField(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: str
    required: bool
    semantic_id: UUID | None = None
    target_type: str | None = None


class InterfaceImplementationBinding(BaseModel):
    implementation: HashedPin
    schema_pin: HashedPin = Field(alias="schema")
    object_type: str
    fields: dict[str, str]


class InterfaceBindings(BaseModel):
    interface: HashedPin
    fields: dict[str, SharedField]
    implementations: list[InterfaceImplementationBinding]


class InterfaceValue(BaseModel):
    object_id: UUID
    object_version_id: UUID
    implementation_resource_id: UUID
    implementation_version_id: UUID
    schema_version_id: UUID
    status: Literal["AVAILABLE", "SCHEMA_CHANGED"]
    values: dict[str, Any] | None


class GroupSchemaBinding(BaseModel):
    object_type: str
    schema_pin: HashedPin = Field(alias="schema")


class TypeGroupBindings(BaseModel):
    group: HashedPin
    schemas: list[GroupSchemaBinding]
    fields: dict[str, SharedField]


class TypeGroupValue(BaseModel):
    object_id: UUID
    object_version_id: UUID
    schema_version_id: UUID
    status: Literal["AVAILABLE", "SCHEMA_CHANGED"]


class ResolvedQuery(ObjectSetQuery):
    valid_at: datetime
    known_at: datetime


class ObjectSetResponse(BaseModel):
    contract: Literal["ontology-object-set/1"]
    query: ResolvedQuery
    total: int = Field(ge=0)
    counts_by_type: dict[str, int]
    objects: list[QueryResource]
    next_offset: int | None = Field(ge=0)
    filter_schema_versions: list[FilterSchemaVersion] = Field(default_factory=list)
    traversal_schema_versions: list[TraversalSchemaVersion] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
    interface_bindings: InterfaceBindings | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    interface_values: list[InterfaceValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    type_group_bindings: TypeGroupBindings | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    type_group_values: list[TypeGroupValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class DefinedObjectSetResponse(ObjectSetResponse):
    definition_id: UUID
    definition_version_id: UUID

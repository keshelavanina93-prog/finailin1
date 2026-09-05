"""Portable ontology queries; no SQL or application-specific joins in callers."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator


class PropertyFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: str = Field(min_length=1, max_length=128)
    value: StrictStr | StrictInt | StrictBool | None


class Traversal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["reference", "link"] = "reference"
    name: str = Field(min_length=1, max_length=128)
    direction: Literal["outgoing", "incoming"] = "outgoing"


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

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Query timestamps must include a timezone")
        return value


class ObjectSetResult(BaseModel):
    contract: Literal["ontology-object-set/1"] = "ontology-object-set/1"
    query: ObjectSetQuery
    total: int
    counts_by_type: dict[str, int]
    objects: list[dict[str, Any]]
    next_offset: int | None

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)


class ResourceMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID = Field(default_factory=uuid4)
    expected_version_id: UUID | None = None
    access_entity: str | None = Field(default=None, min_length=1, max_length=128)
    object_type: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{1,63}$")
    identity_key: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=200)
    attributes: dict[str, Any]
    valid_from: datetime
    valid_to: datetime | None = None
    authority_state: Literal["APPROVED", "REVOKED"] = "APPROVED"
    evidence_class: Literal["USER_ASSERTED", "SOURCE_BOUND", "REFERENCE_TEMPLATE"] = "USER_ASSERTED"

    @model_serializer(mode="wrap")
    def preserve_legacy_payload(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        payload: dict[str, Any] = handler(self)
        if self.access_entity is None:
            payload.pop("access_entity", None)
        return payload

    @field_validator("valid_from", "valid_to")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value and value.tzinfo is None:
            raise ValueError("Effective timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def time_order(self) -> "ResourceMutation":
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("Effective end must follow start")
        return self


class ProposalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=3, max_length=200)
    resource_id: UUID
    attribute_path: list[str] = Field(min_length=1, max_length=16)
    expected: Any


class ResourceProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=3, max_length=200)
    rationale: str = Field(min_length=10, max_length=2000)
    access_entity: str = Field(min_length=1, max_length=128)
    mutations: list[ResourceMutation] = Field(min_length=1, max_length=100)
    expectations: list[ProposalExpectation] = Field(default_factory=list, max_length=100)
    restores_versions: dict[UUID, UUID] = Field(default_factory=dict, max_length=100)
    source_versions: dict[UUID, dict[UUID, UUID]] = Field(default_factory=dict, max_length=100)

    @model_serializer(mode="wrap")
    def preserve_legacy_proposal(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        payload: dict[str, Any] = handler(self)
        if not self.expectations:
            payload.pop("expectations", None)
        if not self.restores_versions:
            payload.pop("restores_versions", None)
        if not self.source_versions:
            payload.pop("source_versions", None)
        return payload

    @model_validator(mode="after")
    def unique_mutations(self) -> "ResourceProposal":
        if len({item.resource_id for item in self.mutations}) != len(self.mutations):
            raise ValueError("A change set may contain only one version per canonical identity")
        mutation_ids = {item.resource_id for item in self.mutations}
        if not set(self.source_versions).issubset(mutation_ids):
            raise ValueError("Source lineage must identify a proposed resource")
        if any(len(versions) > 100 for versions in self.source_versions.values()):
            raise ValueError("At most 100 source versions per proposed resource")
        if any(check.resource_id not in mutation_ids for check in self.expectations):
            raise ValueError("Expectations must bind to a resource in this proposal")
        return self


class ResourceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVED", "REJECTED"]
    rationale: str = Field(min_length=10, max_length=2000)


class CanonicalResource(BaseModel):
    resource_id: UUID
    version_id: UUID
    object_type: str
    identity_key: str
    display_name: str
    access_entity: str
    schema_version_id: UUID | None
    attributes: dict[str, Any]
    content_hash: str
    valid_from: datetime
    valid_to: datetime | None
    system_from: datetime
    authority_state: Literal["APPROVED", "REVOKED"]
    evidence_class: str
    proposal_id: UUID | None


class ProposalDetail(BaseModel):
    proposal: ResourceProposal
    submitted_by: str
    created_at: datetime
    decision: str | None
    reviewed_by: str | None
    review_rationale: str | None
    recorded_at: datetime | None
    validation: dict[str, Any]

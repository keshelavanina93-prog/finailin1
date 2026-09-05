from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

AuthorityState = Literal[
    "OBSERVED",
    "PARSED",
    "MAPPED_CANDIDATE",
    "VALIDATED",
    "RECONCILED",
    "APPROVED",
    "AUTHORITATIVE",
    "CERTIFIED",
    "SUPERSEDED",
    "REVOKED",
]


class VersionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID
    version_id: UUID


class LifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID = Field(default_factory=uuid4)
    subject: VersionReference
    expected_event_id: UUID | None = None
    target_state: AuthorityState
    epistemic_state: Literal["OBSERVED", "DERIVED", "INFERRED"]
    business_state: Literal["PROVISIONAL", "LIVE", "RECONCILED"]
    availability_state: Literal["AVAILABLE", "DEGRADED", "STALE", "UNAVAILABLE", "CONFLICTING"]
    reason: str = Field(min_length=10, max_length=2000)


class LifecycleReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=10, max_length=2000)


class ConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID = Field(default_factory=uuid4)
    consumer: VersionReference
    inputs: list[VersionReference] = Field(min_length=1, max_length=1000)
    minimum_state: AuthorityState = "AUTHORITATIVE"

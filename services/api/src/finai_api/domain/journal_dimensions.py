"""Explicit reviewed account rule completeness and journal-side assignments."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finai_api.domain.resource_lifecycle import VersionReference


class Reasoned(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("reason")
    @classmethod
    def meaningful(cls, value):
        if value != value.strip():
            raise ValueError("An explicit unpadded review reason is required")
        return value


class PolicyDefinition(Reasoned):
    contract: Literal["account-dimension-policy/1"]
    rules: list[VersionReference] = Field(max_length=32)

    @field_validator("rules")
    @classmethod
    def unique(cls, values):
        if len({r.resource_id for r in values}) != len(values):
            raise ValueError("A complete rule policy cannot repeat rule identities")
        return values


class UserAssertion(Reasoned):
    kind: Literal["USER_ASSERTED"]


class SourceAttribution(Reasoned):
    kind: Literal["REVIEWED_SOURCE_ATTRIBUTION"]
    assignment: VersionReference
    side: Literal["DEBIT", "CREDIT"]


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    member: VersionReference
    provenance: Annotated[UserAssertion | SourceAttribution, Field(discriminator="kind")]


class LineDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["journal-line-dimensions/1"]
    policy: VersionReference
    assignments: list[Assignment] = Field(max_length=32)

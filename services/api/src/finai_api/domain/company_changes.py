"""Knowledge-cutoff comparison of explicit retained company context."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.resources import CanonicalResource


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompanyChangesRequest(Model):
    company_id: UUID
    valid_at: AwareDatetime
    known_at: AwareDatetime
    compare_known_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_knowledge(self) -> "CompanyChangesRequest":
        if self.compare_known_at >= self.known_at:
            raise ValueError("The comparison knowledge cutoff must precede the current cutoff")
        return self


class CompanyContextChange(Model):
    resource_id: UUID
    kind: Literal["ADDED_TO_CONTEXT", "REMOVED_FROM_CONTEXT", "CHANGED_VERSION"]
    before: CanonicalResource | None
    after: CanonicalResource | None
    changed_fields: list[str]

    @model_validator(mode="after")
    def exact_sides(self) -> "CompanyContextChange":
        present = (self.before is not None, self.after is not None)
        expected = {
            "ADDED_TO_CONTEXT": (False, True),
            "REMOVED_FROM_CONTEXT": (True, False),
            "CHANGED_VERSION": (True, True),
        }[self.kind]
        if present != expected or any(
            node is not None and node.resource_id != self.resource_id
            for node in (self.before, self.after)
        ):
            raise ValueError("Change sides must match the exact canonical identity and kind")
        if self.kind != "CHANGED_VERSION" and self.changed_fields:
            raise ValueError("Context membership is not a field mutation")
        return self


class CompanyChangesDescriptor(Model):
    contract: Literal["g8-company-changes/1"] = "g8-company-changes/1"
    authority: Literal["RETAINED_COMPANY_CONTEXT_COMPARISON"] = (
        "RETAINED_COMPANY_CONTEXT_COMPARISON"
    )
    coverage: Literal["EXPLICIT_COMPANY_CONTEXT"] = "EXPLICIT_COMPANY_CONTEXT"
    company: CanonicalResource
    valid_at: AwareDatetime
    known_at: AwareDatetime
    compare_known_at: AwareDatetime
    changes: list[CompanyContextChange] = Field(max_length=5000)
    limitations: list[str]
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False

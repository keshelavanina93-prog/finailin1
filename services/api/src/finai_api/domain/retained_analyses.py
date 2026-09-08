"""Discovery references identify historical results; source review establishes the presentation."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.semantic_analysis import Pin


class RetainedAnalysisReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: UUID
    function: Pin
    company: Pin
    title: str = Field(min_length=1, max_length=512)
    receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    valid_at: AwareDatetime
    known_at: AwareDatetime
    recorded_at: AwareDatetime
    projection_contract: Literal["semantic-analysis/1", "semantic-analysis/2"]
    eligibility: Literal["COMPANY_SUBJECT_VERIFIED_SOURCE_REVIEW_REQUIRED"] = (
        "COMPANY_SUBJECT_VERIFIED_SOURCE_REVIEW_REQUIRED"
    )


class RetainedAnalysisPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purpose: Literal["HISTORICAL_COMPANY_ANALYSIS_DISCOVERY"] = (
        "HISTORICAL_COMPANY_ANALYSIS_DISCOVERY"
    )
    company_id: UUID
    observed_at: AwareDatetime
    recorded_before: AwareDatetime
    items: list[RetainedAnalysisReference] = Field(max_length=5)
    inspected_count: int = Field(ge=0, le=5)
    returned_count: int = Field(ge=0, le=5)
    not_listed_count: int = Field(ge=0, le=5)
    next_cursor: str | None
    coverage: Literal["BOUNDED_RETAINED_INVOCATION_PAGE"] = "BOUNDED_RETAINED_INVOCATION_PAGE"
    adapter_scope: Literal["OBJECT_TABLES_AND_GROUPED_OBSERVATIONS_ONLY"] = (
        "OBJECT_TABLES_AND_GROUPED_OBSERVATIONS_ONLY"
    )
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False

    @model_validator(mode="after")
    def consistent_page(self):
        if (
            self.returned_count != len(self.items)
            or self.inspected_count != self.returned_count + self.not_listed_count
            or self.recorded_before > self.observed_at
            or len({item.invocation_id for item in self.items}) != len(self.items)
            or any(
                item.company.resource_id != self.company_id
                or item.recorded_at > self.recorded_before
                for item in self.items
            )
        ):
            raise ValueError("Retained analysis page differs from its scope and scan contract")
        return self

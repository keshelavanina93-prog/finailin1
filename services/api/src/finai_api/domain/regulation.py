"""Executable, typed regulatory interpretations; no embedded legal rates or deadlines."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RegulatoryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    legal_status: Literal["ENACTED", "DRAFT", "POLICY_INTENT"]
    source_version: str = Field(min_length=1, max_length=256)
    source_version_complete: bool
    provision: str = Field(min_length=1, max_length=1000)
    activity: Literal["DISTRIBUTION", "TRANSMISSION", "SUPPLY"]
    effective_from: date
    effective_to: date | None = None
    minimum_customers: int | None = Field(default=None, ge=0)
    obligation: str = Field(min_length=1, max_length=4000)
    deadline: date | None = None
    first_reporting_year: int | None = Field(default=None, ge=1900, le=9999)

    @model_validator(mode="after")
    def ordered_dates(self) -> "RegulatoryDefinition":
        if self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("Effective end must follow start")
        return self


def assess_rule(
    definition: RegulatoryDefinition, at: date, activity: str | None, customer_count: int | None
) -> dict:
    """An assessment of supplied context, never an automatic accounting action."""
    state: str
    if definition.legal_status != "ENACTED":
        state = definition.legal_status
    elif not definition.source_version_complete:
        state = "SOURCE_VERSION_INCOMPLETE"
    elif at < definition.effective_from:
        state = "FUTURE_EFFECTIVE"
    elif definition.effective_to and at >= definition.effective_to:
        state = "EXPIRED"
    else:
        state = "CURRENT_EFFECTIVE"
    if activity is None:
        applicability = "CONTEXT_REQUIRED"
    elif activity != definition.activity:
        applicability = "NOT_APPLICABLE"
    elif definition.minimum_customers is not None and customer_count is None:
        applicability = "CONTEXT_REQUIRED"
    elif (
        definition.minimum_customers is not None
        and customer_count is not None
        and customer_count < definition.minimum_customers
    ):
        applicability = "NOT_APPLICABLE"
    else:
        applicability = "APPLICABLE"
    return {
        "legal_state": state,
        "applicability": applicability,
        "effective_obligation": state == "CURRENT_EFFECTIVE" and applicability == "APPLICABLE",
        "days_to_deadline": (definition.deadline - at).days if definition.deadline else None,
        "obligation": definition.obligation,
    }

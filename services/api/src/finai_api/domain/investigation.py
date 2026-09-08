"""Explicit retained-evidence Action requests; never caller-authored finding facts."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.investigation_resolution import InvestigationResolutionAction
from finai_api.domain.metric_execution import Pin
from finai_api.domain.source_reconciliation_exception import SourceExceptionObservation


class InvestigationAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    rationale: str = Field(min_length=10, max_length=2000)
    expected_finding_version_id: UUID | None = None
    expected_investigation_version_id: UUID | None = None

    @model_validator(mode="after")
    def paired_heads(self):
        if (self.expected_finding_version_id is None) != (
            self.expected_investigation_version_id is None
        ):
            raise ValueError("Finding and Investigation expected heads must be supplied together")
        return self


class FindingDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["source-finding/1"] = "source-finding/1"
    kind: Literal["SOURCE_ROW_WITHOUT_ACCEPTED_JOURNAL"]
    state: Literal["OPEN"] = "OPEN"
    exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    exception_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: SourceExceptionObservation
    financial_impact: None = None
    materiality: Literal["UNASSESSED"] = "UNASSESSED"
    automatic_resolution: Literal[False] = False


class InvestigationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["source-investigation/1"] = "source-investigation/1"
    state: Literal["OPEN"] = "OPEN"
    exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    exception_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    automatic_resolution: Literal[False] = False


class InvestigationPublication(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    finding: Pin
    investigation: Pin


class InvestigationOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: str
    intent_id: str | None = None
    intent_request: InvestigationAction | InvestigationResolutionAction | None = None
    state: Literal["PREPARED", "PENDING_REVIEW", "REJECTED", "PUBLISHED", "PUBLICATION_UNAVAILABLE"]
    proposal: dict[str, Any] | None
    prepared_proposal_id: UUID
    definition: dict[str, Any]
    events: list[dict[str, Any]]
    finding_id: UUID
    investigation_id: UUID
    frozen_rationale: str
    publication: InvestigationPublication | None = None
    publication_limitation: str | None = None
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False

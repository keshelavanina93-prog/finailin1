"""Explicit same-identity resolution evidence; no automatic authority or financial effect."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.metric_execution import Pin
from finai_api.domain.source_reconciliation_exception import SourceExceptionObservation


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InvestigationResolutionAction(Model):
    request_id: UUID
    finding: Pin
    investigation: Pin
    matched_exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    rationale: str = Field(min_length=10, max_length=2000)


class ResolutionProof(Model):
    prior_finding: Pin
    prior_investigation: Pin
    unmatched_exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    unmatched_evidence: SourceExceptionObservation
    matched_exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    matched_evidence: SourceExceptionObservation


class ResolvedFindingDefinition(Model):
    contract: Literal["source-finding/2"] = "source-finding/2"
    kind: Literal["SOURCE_ROW_WITHOUT_ACCEPTED_JOURNAL"] = "SOURCE_ROW_WITHOUT_ACCEPTED_JOURNAL"
    state: Literal["RESOLVED"] = "RESOLVED"
    exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    exception_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: SourceExceptionObservation
    resolution: ResolutionProof
    financial_impact: None = None
    materiality: Literal["UNASSESSED"] = "UNASSESSED"
    automatic_resolution: Literal[False] = False


class ResolvedInvestigationDefinition(Model):
    contract: Literal["source-investigation/2"] = "source-investigation/2"
    state: Literal["RESOLVED"] = "RESOLVED"
    exception_run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")
    exception_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    resolution: ResolutionProof
    automatic_resolution: Literal[False] = False

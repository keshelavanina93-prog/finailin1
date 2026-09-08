"""One source-row reconciliation observation; no Finding or accounting effect authority."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.semantic_analysis import Model, Pin


class SourceExceptionRequest(Model):
    company_id: UUID
    invocation_id: UUID
    journal_snapshot_at: AwareDatetime
    expected_reconciliation_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    coordinate: str = Field(pattern=r"^.{1,128}![A-Z]{1,3}[1-9][0-9]{0,6}$")


class SourceCellReference(Model):
    invocation_id: UUID
    invocation_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence: Pin
    document_id: str = Field(pattern=r"^(doc|ir)_[a-f0-9]{64}$")
    sheet: str
    row: int = Field(ge=1)
    coordinate: str


class ReconciliationReference(Model):
    receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["UNAVAILABLE", "PARTIAL", "RECONCILED"]


class SourceExceptionObservation(Model):
    contract: Literal["source-reconciliation-exception/1"] = "source-reconciliation-exception/1"
    detector: Literal["source-reconciliation-exceptions/1"] = "source-reconciliation-exceptions/1"
    company: Pin
    selection: dict[str, VersionReference]
    context_versions: list[Pin] = Field(min_length=7, max_length=7)
    binding: Pin
    source_function: Pin
    source: SourceCellReference
    source_valid_at: AwareDatetime
    source_known_at: AwareDatetime
    journal_observed_at: AwareDatetime
    reconciliation: ReconciliationReference
    state: Literal["UNMATCHED_AT_SNAPSHOT", "MATCHED_AT_SNAPSHOT", "EXCLUDED_SOURCE_VALUE"]
    finding_eligible: bool
    exclusion_reason: str | None = None
    matched_journals: list[VersionReference] = Field(default_factory=list)
    financial_impact: None = None
    materiality: Literal["UNASSESSED"] = "UNASSESSED"
    automatic_resolution: Literal[False] = False
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False
    receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def state_consistency(self):
        if self.finding_eligible != (self.state == "UNMATCHED_AT_SNAPSHOT"):
            raise ValueError("Only unmatched source rows can seed a finding")
        if bool(self.matched_journals) != (self.state == "MATCHED_AT_SNAPSHOT"):
            raise ValueError("Only matched rows carry accepted journal references")
        if (self.exclusion_reason is not None) != (self.state == "EXCLUDED_SOURCE_VALUE"):
            raise ValueError("Excluded source rows must retain their reason")
        return self

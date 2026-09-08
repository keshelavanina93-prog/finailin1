"""Reference-only composition and immutable saved analytical report contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from finai_api.domain.authority import ExactScope
from finai_api.domain.semantic_analysis import Contributor, Filter, Model, Pin, Projection


class ReportSectionReference(Model):
    section_id: UUID
    title: str = Field(min_length=1, max_length=200)
    invocation_id: UUID
    receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    descriptor_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    columns: list[str] = Field(min_length=1, max_length=32)
    filters: list[Filter] = Field(default_factory=list, max_length=4)
    group_by: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def unique_selection(self):
        if len(set(self.columns)) != len(self.columns) or any(
            not key or len(key) > 128 for key in self.columns
        ):
            raise ValueError("Report columns must be unique bounded field keys")
        if len({item.field for item in self.filters}) != len(self.filters):
            raise ValueError("A report section may filter a field only once")
        return self


class ReportComposition(Model):
    company_id: UUID
    valid_at: datetime
    known_at: datetime
    title: str = Field(min_length=1, max_length=200)
    commentary: str = Field(default="", max_length=8000)
    sections: list[ReportSectionReference] = Field(min_length=1, max_length=8)

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware_time(cls, value: datetime):
        if value.tzinfo is None:
            raise ValueError("Company snapshot timestamps require a timezone")
        return value

    @model_validator(mode="after")
    def unique_sections(self):
        if len({item.section_id for item in self.sections}) != len(self.sections):
            raise ValueError("Report section identities must be unique")
        return self


class ReportSectionResult(Model):
    reference: ReportSectionReference
    projection: Projection
    contributors: dict[str, list[Contributor]] = Field(max_length=1000)
    authority_observation: dict[str, Any]
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False


class RetainedReportSnapshot(Model):
    contract: Literal["retained-report-snapshot/1"] = "retained-report-snapshot/1"
    composition: ReportComposition
    company: Pin
    company_label: str
    sections: list[ReportSectionResult] = Field(min_length=1, max_length=8)
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False


class ReportPreview(Model):
    contract: Literal["retained-report-preview/1"] = "retained-report-preview/1"
    snapshot: RetainedReportSnapshot
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SaveRetainedReport(Model):
    request_id: UUID
    report_id: UUID
    previous_proposal_id: UUID | None = None
    expected_preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    composition: ReportComposition


class ReportArtifact(Model):
    media_type: str
    filename: str
    size_bytes: int = Field(ge=1, le=16_000_000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_base64: str = Field(max_length=22_000_000)


class RetainedReportDefinition(Model):
    contract: Literal["retained-report-definition/1"] = "retained-report-definition/1"
    report_id: UUID
    exact_scope: ExactScope
    previous_proposal_id: UUID | None = None
    expected_preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot: RetainedReportSnapshot
    exports: dict[Literal["xlsx", "html"], ReportArtifact]

    @model_validator(mode="after")
    def formats(self):
        if set(self.exports) != {"xlsx", "html"}:
            raise ValueError("A saved report requires both exact export artifacts")
        return self

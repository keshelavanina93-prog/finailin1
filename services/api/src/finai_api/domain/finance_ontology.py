"""Finance domain definition and installation requests over canonical resources."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FinanceCapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str = Field(pattern=r"^[A-Z_]{2,60}$")
    name: str = Field(min_length=1, max_length=150)
    purpose: str = Field(min_length=10, max_length=2000)
    required_evidence: list[str] = Field(min_length=1, max_length=30)
    dimensions: list[str] = Field(max_length=30)
    process_types: list[str] = Field(max_length=30)
    fact_grains: list[
        Literal[
            "TRANSACTION",
            "JOURNAL_LINE",
            "ACCOUNT_PERIOD",
            "FS_ITEM_PERIOD",
            "REPORT_LINE_PERIOD",
            "PLANNING_CELL",
        ]
    ] = Field(min_length=1, max_length=6)
    calculation_policy_required: bool = True
    source_module_identity: Literal["SOURCE_EVIDENCE_REQUIRED"] = "SOURCE_EVIDENCE_REQUIRED"


class CatalogProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    phase: str = Field(min_length=1, max_length=64)
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=40, ge=1, le=75)
    valid_from: datetime
    rationale: str = Field(min_length=10, max_length=2000)
    request_id: UUID

    @field_validator("valid_from")
    @classmethod
    def timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Effective timestamp requires a timezone")
        return value


class FinanceCatalogView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_id: str
    catalog_sha256: str
    manifest: dict[str, Any]
    diagnostics: list[Any]
    definitions: list[dict[str, Any]]
    phases: list[dict[str, Any]]
    ready: bool
    company_facts_published: Literal[False] = False

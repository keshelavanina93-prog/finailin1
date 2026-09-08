"""Supported accepted-movement metrics; no statement or canonical publication authority."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.semantic_analysis import Model, Pin

MetricKey = Literal["debit_movement", "credit_movement", "net_movement"]


class FinancialMetricRequest(Model):
    invocation_id: UUID
    company_id: UUID
    snapshot_at: datetime
    expected_reconciliation_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    expected_result_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("snapshot_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Financial metric snapshot must include a timezone")
        return value


class MetricRecipe(Model):
    code: MetricKey
    label: str
    function_reference: Literal["finance.accepted-journal-movements/v1"] = (
        "finance.accepted-journal-movements/v1"
    )
    definition_authority: Literal["CODE_DEFINED_NOT_PUBLISHED"] = "CODE_DEFINED_NOT_PUBLISHED"
    operation: Literal["ACCEPTED_DEBIT", "ACCEPTED_CREDIT", "DEBIT_MINUS_CREDIT"]
    unit: VersionReference
    unit_label: str | None = None


class MetricValue(Model):
    state: Literal["VALUE", "UNAVAILABLE"]
    value: str | None = Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")

    @model_validator(mode="after")
    def availability(self):
        if (self.state == "VALUE") != (self.value is not None):
            raise ValueError("Unavailable metric is null; numeric zero remains a value")
        return self


class JournalContribution(Model):
    journal: VersionReference
    lines: list[VersionReference] = Field(min_length=2, max_length=2)
    dimension_policies: list[VersionReference] = Field(min_length=1, max_length=2)
    source_coordinate: str


class MetricNode(Model):
    key: str
    parent_key: str | None
    kind: Literal["COMPANY_MOVEMENTS", "ACCOUNT_MOVEMENTS"]
    label: str
    account_code: str | None = None
    subject: Pin
    metrics: dict[MetricKey, MetricValue]
    source_coordinates: list[str]
    journal_keys: list[str]
    analysis_row_key: str | None = None

    @model_validator(mode="after")
    def supported_metrics(self):
        if set(self.metrics) != {"debit_movement", "credit_movement", "net_movement"}:
            raise ValueError("Metric node requires the complete supported movement set")
        return self


class FinancialMetricCoverage(Model):
    state: Literal["UNAVAILABLE", "PARTIAL", "RECONCILED"]
    source_rows: int
    literal_source_rows: int
    accepted_journals: int
    unmatched_source_rows: int
    excluded_source_rows: int
    rejected_journals: int
    missing_coordinates: list[str]
    excluded_rows: list[dict]
    rejected: list[dict]
    ledger_completeness: Literal["UNESTABLISHED"] = "UNESTABLISHED"


class FinancialMetricResult(Model):
    contract: Literal["company-financial-metrics/1"] = "company-financial-metrics/1"
    invocation_id: UUID
    company_id: UUID
    snapshot_at: datetime
    selection: dict[str, VersionReference]
    binding: Pin
    source_function: Pin
    source_sha256: str
    source_receipt_hash: str
    reconciliation_receipt_hash: str
    implementation_sha256: str
    definitions: list[MetricRecipe]
    nodes: list[MetricNode]
    journals: list[JournalContribution]
    coverage: FinancialMetricCoverage
    hierarchy_basis: Literal["COMPANY_AND_EXACT_LOCAL_ACCOUNT"] = "COMPANY_AND_EXACT_LOCAL_ACCOUNT"
    aggregation: Literal["SERVER_OWNED_VALUES_DO_NOT_SUM_HIERARCHY"] = (
        "SERVER_OWNED_VALUES_DO_NOT_SUM_HIERARCHY"
    )
    unavailable: list[str] = Field(
        default_factory=lambda: [
            "OPENING_BALANCE",
            "CLOSING_BALANCE",
            "STATEMENT_MAPPING",
            "FINANCIAL_STATEMENTS",
            "CERTIFICATION",
        ]
    )
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False
    result_sha256: str

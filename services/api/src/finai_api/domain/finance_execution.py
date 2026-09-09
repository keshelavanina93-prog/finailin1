"""Reviewed finance calculations over existing fact contracts and resource versions."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finai_api.domain.authority import ExactScope
from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.resource_lifecycle import VersionReference


class FinanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectionRule(FinanceModel):
    account: VersionReference
    reporting_line: VersionReference
    multiplier: Literal["1", "-1"]
    rationale: str = Field(min_length=10, max_length=2000)


class FinanceProjectionDefinition(FinanceModel):
    contract: Literal["finance-projection/1"] = "finance-projection/1"
    projection_code: Literal["CORPORATE_MR", "PETROLEUM_PNL", "GAS"]
    exact_scope: ExactScope
    fact_contract: VersionReference
    company: VersionReference
    chart: VersionReference
    evidence: VersionReference
    starts_on: date
    ends_on: date
    source_family: str = Field(min_length=1, max_length=128)
    account_field: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")
    unit_value: str = Field(min_length=1, max_length=128)
    rules: list[ProjectionRule] = Field(min_length=1, max_length=1000)
    expected_accounts: list[VersionReference] = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def coherent_projection(self):
        if self.starts_on > self.ends_on:
            raise ValueError("Projection coverage starts after it ends")
        accounts = [rule.account.resource_id for rule in self.rules]
        if len(set(accounts)) != len(accounts):
            raise ValueError("An account may contribute to one leaf line per projection")
        expected = [ref.resource_id for ref in self.expected_accounts]
        if len(set(expected)) != len(expected):
            raise ValueError("Expected accounts must be distinct exact versions")
        if set(expected) != set(accounts):
            raise ValueError("Every expected account requires exactly one explicit mapping")
        versions = {ref.resource_id: ref.version_id for ref in self.expected_accounts}
        if any(
            versions[rule.account.resource_id] != rule.account.version_id for rule in self.rules
        ):
            raise ValueError("Projection mappings and coverage must pin the same account versions")
        lines = {}
        for rule in self.rules:
            line = rule.reporting_line
            if line.resource_id in lines and lines[line.resource_id] != line.version_id:
                raise ValueError("A reporting line must use one exact version per projection")
            lines[line.resource_id] = line.version_id
        if self.ends_on.strftime("%Y-%m") != self.exact_scope.period:
            raise ValueError("Projection end must belong to its exact scope period")
        return self


class FinanceExecutionRequest(FinanceModel):
    operation: Literal["trial_balance", "closing_as_of", "ytd_flow", "reconcile_parent", "project"]
    contract: VersionReference
    query: ObjectSetQuery
    group_by: list[str] = Field(default_factory=list, max_length=20)
    starts_on: date | None = None
    as_of: date
    account_field: str = Field(default="account_id", pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")
    side_field: str | None = Field(default=None, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,127}$")
    projection: VersionReference | None = None

    @model_validator(mode="after")
    def exact_execution(self):
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("Finance grouping dimensions must be distinct")
        if self.query.traversal or self.query.interface or self.query.type_group:
            raise ValueError("Finance execution consumes one direct fact representation")
        if self.query.offset != 0:
            raise ValueError("Finance execution requires a complete query starting at zero")
        if self.query.valid_at is None or self.query.known_at is None:
            raise ValueError("Finance execution requires exact valid and known timestamps")
        if self.operation in {"trial_balance", "ytd_flow", "project"} and self.starts_on is None:
            raise ValueError("Flow execution requires an explicit coverage start")
        if self.starts_on is not None and self.starts_on > self.as_of:
            raise ValueError("Finance coverage starts after it ends")
        if self.operation == "ytd_flow" and (
            self.starts_on is None or (self.as_of - self.starts_on).days > 365
        ):
            raise ValueError("YTD requires an explicit fiscal-year start within one year")
        if (self.operation == "project") != (self.projection is not None):
            raise ValueError("Only project execution requires an exact reviewed projection")
        if self.side_field is not None and self.operation != "trial_balance":
            raise ValueError("Journal posting side is only supported for trial-balance turnover")
        return self


class FinanceGroup(FinanceModel):
    dimensions: dict[str, str | int | bool | None]
    value: str | None
    state: Literal["DERIVED", "INCOMPLETE", "UNAVAILABLE"] = "DERIVED"
    observed_value: str | None = None
    inputs: list[VersionReference]
    missing: list[str] = Field(default_factory=list)
    debit_turnover: str | None = None
    credit_turnover: str | None = None
    opening_balance: str | None = None
    closing_balance: str | None = None


class FinanceCalculation(FinanceModel):
    contract: Literal["finance-calculation/1"] = "finance-calculation/1"
    operation: str
    state: Literal["DERIVED", "INCOMPLETE", "UNAVAILABLE", "MATCHED", "UNRECONCILED"]
    starts_on: date | None
    as_of: date
    input_count: int = Field(ge=0)
    input_grain: list[str]
    unit_field: str
    partition_fields: list[str]
    groups: list[FinanceGroup] = Field(default_factory=list)
    comparisons: list[dict] = Field(default_factory=list)
    missing_accounts: list[str] = Field(default_factory=list)
    unmapped_accounts: list[str] = Field(default_factory=list)
    coverage: Literal["SELECTED_FACTS_ONLY", "EXPLICIT_PERIOD_INTERVALS"]
    authority: Literal["SOURCE_BOUND_ANALYSIS"] = "SOURCE_BOUND_ANALYSIS"
    financial_certification: None = None
    business_effect_authorized: Literal[False] = False
    current_use_authorized: Literal[False] = False


class CanonicalJournalTrialBalanceRequest(FinanceModel):
    company: VersionReference
    ledger: VersionReference
    book: VersionReference
    period: VersionReference
    snapshot_at: datetime
    starts_on: date
    as_of: date
    max_journals: int = Field(default=200, strict=True, ge=1, le=200)

    @field_validator("snapshot_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Journal snapshot requires an exact timezone-aware timestamp")
        return value

    @model_validator(mode="after")
    def period_order(self):
        if self.starts_on > self.as_of:
            raise ValueError("Journal coverage starts after it ends")
        return self

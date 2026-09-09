"""Explicit, reviewable interpretation rules for retained rows, including missing account codes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.authority import ExactScope
from finai_api.domain.resource_lifecycle import VersionReference


class ClassificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RowCondition(ClassificationModel):
    field: str = Field(min_length=1, max_length=128)
    operator: Literal["equals", "contains", "starts_with"] = "equals"
    value: str = Field(min_length=1, max_length=500)
    case_sensitive: bool = False


class ClassificationRule(ClassificationModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")
    conditions: list[RowCondition] = Field(min_length=1, max_length=20)
    account: VersionReference
    grain: Literal[
        "TRANSACTION",
        "JOURNAL_LINE",
        "ACCOUNT_PERIOD",
        "FS_ITEM_PERIOD",
        "REPORT_LINE_PERIOD",
        "PLANNING_CELL",
    ]
    side: Literal["DR", "CR"] | None = None
    process_type: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=10, max_length=2000)


class FinanceClassificationPolicy(ClassificationModel):
    contract: Literal["finance-classification/1"] = "finance-classification/1"
    exact_scope: ExactScope
    company: VersionReference
    chart: VersionReference
    evidence: VersionReference
    source_format: Literal["csv", "xlsx", "xls", "json"]
    source_family: str = Field(min_length=1, max_length=128)
    sheet: str | None = Field(default=None, max_length=128)
    header_row: int = Field(default=1, ge=1, le=100)
    columns: list[str] = Field(min_length=1, max_length=256)
    amount_field: str = Field(min_length=1, max_length=128)
    date_field: str = Field(min_length=1, max_length=128)
    identity_field: str = Field(min_length=1, max_length=128)
    currency_field: str = Field(min_length=1, max_length=128)
    decimal_format: Literal["DOT", "COMMA"] = "DOT"
    dimension_fields: dict[str, str] = Field(default_factory=dict, max_length=30)
    required_dimensions: list[str] = Field(default_factory=list, max_length=30)
    rules: list[ClassificationRule] = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def complete_policy(self) -> "FinanceClassificationPolicy":
        if len(set(self.columns)) != len(self.columns) or len({r.key for r in self.rules}) != len(
            self.rules
        ):
            raise ValueError("Source columns and classification rule keys must be unique")
        referenced = {
            self.amount_field,
            self.date_field,
            self.identity_field,
            self.currency_field,
            *self.dimension_fields.values(),
            *(c.field for r in self.rules for c in r.conditions),
        }
        if not referenced.issubset(self.columns):
            raise ValueError("Every policy input must name a retained source column")
        if not set(self.required_dimensions).issubset(self.dimension_fields):
            raise ValueError("Required dimensions need explicit source-column bindings")
        if self.source_format in {"xlsx", "xls"} and not self.sheet:
            raise ValueError("Workbook policy requires an exact worksheet")
        return self


class ClassificationRequest(ClassificationModel):
    policy: VersionReference
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")
    offset: int = Field(default=0, ge=0, le=30000)
    limit: int = Field(default=25, ge=1, le=100)

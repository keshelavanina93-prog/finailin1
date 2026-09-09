"""Contracts for the governed 2025 SOCAR Georgia Petroleum intake package.

The package is a historical evidence view.  It never promotes the observed
balances to accounting authority; mapping approval remains a separate gate.
"""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrialBalancePackageFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(pattern=r"^SGP (?:[1-9]|1[0-2])\.xls$", max_length=32)
    xls_base64: str = Field(min_length=1, max_length=5_333_336)


class TrialBalancePackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    year: Literal[2025] = 2025
    files: tuple[TrialBalancePackageFile, ...] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def require_one_file_per_month(self) -> Self:
        names = [item.filename for item in self.files]
        if len(set(names)) != 12:
            raise ValueError("The 2025 package requires one unique SGP workbook for every month")
        months = sorted(int(name.removesuffix(".xls").split()[-1]) for name in names)
        if months != list(range(1, 13)):
            raise ValueError("The 2025 package requires SGP 1.xls through SGP 12.xls")
        return self


class TrialBalanceCarryforward(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_period: str | None
    to_period: str
    opening_debit: str | None
    prior_closing_debit: str | None
    debit_delta: str | None
    opening_credit: str | None
    prior_closing_credit: str | None
    credit_delta: str | None
    state: Literal["NOT_APPLICABLE", "PASS", "BREAK"]


class TrialBalanceMonthProof(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    period: str
    source_sha256: str
    row_count: int = Field(ge=0)
    selected_root_rows: int = Field(ge=0)
    source_total_rows: tuple[int, ...]
    totals: dict[str, str]
    pair_deltas: dict[str, str]
    hierarchy_check_count: int = Field(ge=0)
    hierarchy_breaks: int = Field(ge=0)
    equality: dict[str, Literal["PASS", "BREAK"]]
    equality_state: Literal["PASS", "BREAK"]
    mapping_state: Literal["REQUIRED", "APPROVED"] = "REQUIRED"
    receipt_id: str | None = None


class TrialBalancePackageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    package_id: str
    tenant_id: UUID | None = None
    legal_entity_id: str | None = None
    entity_label: str
    year: Literal[2025] = 2025
    currency: str
    workbook_count: int = 12
    row_count: int
    expected_row_count: int = 38137
    row_count_state: Literal["PASS", "BREAK"]
    periods: tuple[str, ...]
    months: tuple[TrialBalanceMonthProof, ...]
    carryforward: tuple[TrialBalanceCarryforward, ...]
    carryforward_breaks: int = Field(ge=0)
    hierarchy_breaks: int = Field(ge=0)
    package_evidence_state: Literal["SOURCE_PROOF_PASSED", "SOURCE_REVIEW_REQUIRED"]
    mapping_state: Literal["REQUIRED", "APPROVED"] = "REQUIRED"
    finance_locked: bool = True
    planning_locked: bool = True
    reporting_locked: bool = True
    historical_scope_guard: dict[str, str | bool]
    account_codes: tuple[str, ...]


class TrialBalancePackageDiagnosticsRequest(BaseModel):
    """Read-only diagnostic input; it cannot change package or mapping state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report: TrialBalancePackageReport


class TrialBalanceDiagnosticFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[A-Z0-9_]+$", max_length=64)
    severity: Literal["INFO", "WARNING", "ERROR"]
    state: Literal["PASS", "REVIEW_REQUIRED", "LOCKED", "BLOCKED"]
    message: str = Field(min_length=1, max_length=500)
    periods: tuple[str, ...] = ()


class TrialBalancePackageDiagnostics(BaseModel):
    """Deterministic diagnostics for a historical package in an operator scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    package_id: str
    tenant_id: UUID
    legal_entity_id: str
    source_year: Literal[2025] = 2025
    source_periods: tuple[str, ...]
    active_runtime_period: str
    evaluated_under_active_runtime_period: bool
    historical_scope_state: Literal["ISOLATED", "REVIEW_REQUIRED"]
    evidence_state: Literal["SOURCE_PROOF_PASSED", "SOURCE_REVIEW_REQUIRED"]
    mapping_state: Literal["REQUIRED", "APPROVED"]
    finance_locked: bool
    planning_locked: bool
    reporting_locked: bool
    carryforward_breaks: int = Field(ge=0)
    overall_state: Literal["PASS", "REVIEW_REQUIRED", "BLOCKED"]
    findings: tuple[TrialBalanceDiagnosticFinding, ...]

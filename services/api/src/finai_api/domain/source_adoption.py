"""Explicit recurring-source compatibility over shared accounting identities.

These snapshots are derived by the server from retained source bytes and reviewed
canonical resources. Request models accept references, never asserted compatibility.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finai_api.domain.resource_lifecycle import VersionReference

SourceProfile = Literal["1c_tb", "1c_journal", "seg_expense_base"]
AdoptionPolicy = Literal["DISJOINT_PERIOD_ADDITION", "REPLACES_PREDECESSOR_SNAPSHOT"]


class PinnedResource(VersionReference):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class SourceFamilySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    family_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,95}$")
    source_system: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    display_name: str = Field(min_length=3, max_length=200)
    baseline_binding: VersionReference
    rationale: str = Field(min_length=10, max_length=2000)

    @field_validator("rationale")
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 10:
            raise ValueError("Explain the stable source family and its accounting meaning")
        return value.strip()


class SourceAdoptionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    family: VersionReference
    predecessor_binding: VersionReference
    successor_binding: VersionReference
    predecessor_adoption: VersionReference | None = None
    policy: AdoptionPolicy
    rationale: str = Field(min_length=10, max_length=2000)

    @field_validator("rationale")
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 10:
            raise ValueError("Explain successor compatibility and the coverage policy")
        return value.strip()


class AccountingMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ledger: PinnedResource
    book: PinnedResource
    currency: PinnedResource
    functional_currency: PinnedResource
    account_mapping: PinnedResource
    dimension_mapping: PinnedResource
    transaction_currency: PinnedResource | None = None
    reporting_currency: PinnedResource | None = None
    currency_role: Literal["FUNCTIONAL", "TRANSACTION", "PRESENTATION"]
    currency_policy: Literal["SOURCE_AMOUNT_ONLY", "MULTI_CURRENCY"]
    granularity: Literal["SOURCE_ROW", "PERIOD_ACCOUNT"]
    deepest_valid_drill: Literal["SOURCE_CELL", "SOURCE_ROW", "PERIOD_ACCOUNT"]
    amount_field: str = Field(min_length=1, max_length=128)
    amount_semantics: Literal["DEBIT_CREDIT", "SIGNED_MOVEMENT", "PERIOD_BALANCE"]
    vat_treatment: Literal["AS_POSTED"] | None = None
    supplementary_amount_field: str | None = None
    supplementary_amount_role: Literal["NON_AUTHORITATIVE_SOURCE_OBSERVATION"] | None = None


class SourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    binding: PinnedResource
    scope: PinnedResource
    evidence: PinnedResource
    company: PinnedResource
    chart: PinnedResource
    company_alias: PinnedResource | None = None
    period: PinnedResource
    period_starts_on: date
    period_ends_on: date
    observed_from: date
    observed_through: date
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document_id: str = Field(min_length=1, max_length=256)
    worksheet: str = Field(min_length=1, max_length=128)
    source_profile: SourceProfile
    date_basis: Literal["EXPLICIT_REPORT_PERIOD", "OBSERVED_MOVEMENT_DATE_EXTENT"]
    source_rows: int = Field(ge=1, le=100000, strict=True)
    coverage_state: Literal["UNESTABLISHED"] = "UNESTABLISHED"
    missing_amount_count: int = Field(ge=0, le=100000, strict=True)
    missing_amount_coordinates: list[str] = Field(max_length=100)
    meaning: AccountingMeaning

    @model_validator(mode="after")
    def dates_are_within_reviewed_period(self):
        if not (
            self.period_starts_on
            <= self.observed_from
            <= self.observed_through
            <= self.period_ends_on
        ):
            raise ValueError("Source dates must lie inside their own reviewed period")
        if (
            self.missing_amount_count > self.source_rows
            or len(self.missing_amount_coordinates) != min(self.missing_amount_count, 100)
            or len(set(self.missing_amount_coordinates)) != len(self.missing_amount_coordinates)
        ):
            raise ValueError("Retain the missing-amount count and first 100 unique coordinates")
        return self


class FamilyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    selection: SourceFamilySelection
    baseline: SourceSnapshot


class AdoptionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    selection: SourceAdoptionSelection
    family: PinnedResource
    predecessor: SourceSnapshot
    successor: SourceSnapshot


def require_same_family(baseline: SourceSnapshot, candidate: SourceSnapshot) -> None:
    """Matching layout alone cannot authorize inherited accounting meaning."""
    if (
        baseline.company.resource_id != candidate.company.resource_id
        or baseline.chart.resource_id != candidate.chart.resource_id
    ):
        raise ValueError("A recurring source must retain its canonical company and chart")
    if (
        baseline.source_profile != candidate.source_profile
        or baseline.worksheet != candidate.worksheet
        or baseline.schema_sha256 != candidate.schema_sha256
        or baseline.date_basis != candidate.date_basis
    ):
        raise ValueError("Source schema, profile or date interpretation changed")
    if baseline.meaning != candidate.meaning:
        raise ValueError("Reviewed accounting meaning or exact mapping versions changed")


def require_compatible_adoption(
    baseline: SourceSnapshot,
    predecessor: SourceSnapshot,
    successor: SourceSnapshot,
    policy: AdoptionPolicy,
) -> None:
    require_same_family(baseline, predecessor)
    require_same_family(baseline, successor)
    if (
        predecessor.source_sha256 == successor.source_sha256
        or predecessor.binding.resource_id == successor.binding.resource_id
        or predecessor.scope.resource_id == successor.scope.resource_id
    ):
        raise ValueError("Adoption requires a distinct immutable successor snapshot")
    if successor.source_sha256 == baseline.source_sha256:
        raise ValueError("The original family snapshot cannot be reintroduced as a new successor")
    if policy == "DISJOINT_PERIOD_ADDITION":
        if successor.period_starts_on <= predecessor.period_ends_on:
            raise ValueError("Additional coverage must use a later disjoint reviewed period")
        if successor.period.resource_id == predecessor.period.resource_id:
            raise ValueError("A later source must retain its own reviewed period identity")
    elif policy == "REPLACES_PREDECESSOR_SNAPSHOT":
        if (
            successor.period != predecessor.period
            or successor.period_starts_on != predecessor.period_starts_on
            or successor.period_ends_on != predecessor.period_ends_on
        ):
            raise ValueError("Replacement requires the exact same reviewed period")
    else:
        raise ValueError("An explicit reviewed overlap policy is required")

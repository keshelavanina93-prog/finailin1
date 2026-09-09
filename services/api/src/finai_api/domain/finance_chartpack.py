"""Declarative ChartPack contracts for generic account-period classification.

ChartPacks are reviewed data, not product code.  They describe how an observed
account code may be proposed for a reporting line; they do not create an
accepted account, journal, currency, or business effect.  The runtime keeps
the mapping state ``proposed`` until the normal independent review path
accepts the resulting proposal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChartPackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalyticRule(ChartPackModel):
    """A source-label pattern used to split an account's observed analytics."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,80}$")
    source_pattern: str = Field(min_length=1, max_length=300)
    dimension: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    priority: int = Field(default=0, ge=0, le=10_000)
    rationale: str = Field(min_length=10, max_length=1000)


class AnalyticPolicy(ChartPackModel):
    """Declarative analytics policy attached to a ChartPack account class."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,80}$")
    source_field: str = Field(pattern=r"^[a-z][a-z0-9_]{1,80}$")
    rules: list[AnalyticRule] = Field(default_factory=list, max_length=30)
    default_dimension: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,80}$")
    rationale: str = Field(min_length=10, max_length=1500)

    @model_validator(mode="after")
    def unique_rule_keys(self) -> AnalyticPolicy:
        keys = [rule.key for rule in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("Analytic policy rule keys must be unique")
        if not self.rules and self.default_dimension is None:
            raise ValueError("Analytic policy requires a rule or default dimension")
        return self


class ChartPackRule(ChartPackModel):
    """One account-code class and its draft reporting semantics."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,80}$")
    account_pattern: str = Field(min_length=1, max_length=300)
    local_account_class: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,100}$")
    statement_line: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,100}$")
    flow_measure: Literal["turnover_debit", "turnover_credit"] | None = None
    balance_measure: Literal[
        "opening_debit",
        "opening_credit",
        "closing_debit",
        "closing_credit",
    ] | None = None
    analytic_policy: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{1,80}$")
    operating: bool = True
    priority: int = Field(default=0, ge=0, le=10_000)
    rationale: str = Field(min_length=10, max_length=1500)


class ChartPack(ChartPackModel):
    """Versioned, reusable mapping data for one source chart family."""

    contract: Literal["chartpack/1"] = "chartpack/1"
    pack_id: str = Field(pattern=r"^chartpack\.[a-z0-9_.-]{3,120}$")
    version: int = Field(ge=1, le=10_000)
    display_name: str = Field(min_length=3, max_length=200)
    jurisdiction: str = Field(min_length=2, max_length=32)
    source_classes: list[str] = Field(min_length=1, max_length=20)
    mapping_status: Literal["proposed", "accepted"] = "proposed"
    authority: Literal["CANDIDATE_ONLY"] = "CANDIDATE_ONLY"
    currency_status: Literal["UNREVIEWED", "REVIEWED"] = "UNREVIEWED"
    rules: list[ChartPackRule] = Field(min_length=1, max_length=500)
    analytic_policies: list[AnalyticPolicy] = Field(default_factory=list, max_length=100)
    rationale: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def coherent_pack(self) -> ChartPack:
        rule_keys = [rule.key for rule in self.rules]
        if len(set(rule_keys)) != len(rule_keys):
            raise ValueError("ChartPack rule keys must be unique")
        policy_keys = [policy.key for policy in self.analytic_policies]
        if len(set(policy_keys)) != len(policy_keys):
            raise ValueError("ChartPack analytic policy keys must be unique")
        policies = set(policy_keys)
        if any(rule.analytic_policy not in policies for rule in self.rules if rule.analytic_policy):
            raise ValueError("ChartPack rule references an unknown analytic policy")
        return self


class AccountClassification(ChartPackModel):
    """A deterministic, still-unreviewed classification result."""

    account_code: str
    normalized_account_code: str
    state: Literal["CLASSIFICATION_UNREVIEWED", "UNMAPPED", "AMBIGUOUS"]
    mapping_status: Literal["proposed"] = "proposed"
    rule_key: str | None = None
    local_account_class: str | None = None
    statement_line: str | None = None
    flow_measure: Literal["turnover_debit", "turnover_credit"] | None = None
    balance_measure: Literal[
        "opening_debit",
        "opening_credit",
        "closing_debit",
        "closing_credit",
    ] | None = None
    analytic_policy: str | None = None
    analytic_dimension: str | None = None
    operating: bool | None = None
    additive_ok: bool = True
    duplicate_of: int | None = None
    reason: str

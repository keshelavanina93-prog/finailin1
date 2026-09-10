"""Evidence-gated 1C account-family dimension policies.

The workbook gives us labels and observed column order. It does not, by itself,
authorize a posting rule. This module keeps that distinction executable: a
family can be recognized, but dimensions remain UNKNOWN until a reviewed rule
receipt says they are binding.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DimensionPolicyTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_family_pattern: str = Field(min_length=1, max_length=128)
    required_dimensions: list[str] = Field(min_length=1, max_length=20)
    observed_slot_order: list[str] = Field(min_length=1, max_length=20)
    evidence_state: Literal["OBSERVED_LABEL_ONLY", "RULE_EVIDENCED", "UNKNOWN"]
    slot_note: str = Field(min_length=10, max_length=1000)


class DimensionValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_code: str = Field(min_length=1, max_length=128)
    bindings: dict[str, str | None] = Field(default_factory=dict, max_length=30)
    evidence_state: Literal["OBSERVED_LABEL_ONLY", "RULE_EVIDENCED", "UNKNOWN"] = (
        "OBSERVED_LABEL_ONLY"
    )


def _catalog() -> dict:
    resource = files("finai_api").joinpath("catalog", "finance-domain.g8.v1.json")
    if resource.is_file():
        return json.loads(resource.read_text(encoding="utf-8"))
    path = (
        Path(__file__).resolve().parents[5]
        / "packages/contracts/catalog/finance-domain.g8.v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def policies() -> list[DimensionPolicyTemplate]:
    return [
        DimensionPolicyTemplate.model_validate(row)
        for row in _catalog()["account_dimension_policies"]
    ]


def match(account_code: str) -> DimensionPolicyTemplate | None:
    for policy in policies():
        if re.match(policy.account_family_pattern, account_code):
            return policy
    return None


def validate(request: DimensionValidationRequest) -> dict:
    policy = match(request.account_code)
    if policy is None:
        return {
            "account_code": request.account_code,
            "state": "UNKNOWN",
            "matched_policy": None,
            "required_dimensions": [],
            "observed_slot_order": [],
            "missing_dimensions": [],
            "bindings": request.bindings,
            "reason": "No source-supported account-family policy is pinned",
        }
    missing = [name for name in policy.required_dimensions if not request.bindings.get(name)]
    state: str = request.evidence_state
    reason = policy.slot_note
    if state != "RULE_EVIDENCED":
        state = "OBSERVED_LABEL_ONLY"
        reason = "Observed subkonto labels do not authorize a posting rule"
    elif missing:
        state = "INCOMPLETE"
        reason = "A reviewed rule exists, but a required dimension is missing"
    return {
        "account_code": request.account_code,
        "state": state,
        "matched_policy": policy.account_family_pattern,
        "required_dimensions": policy.required_dimensions,
        "observed_slot_order": policy.observed_slot_order,
        "missing_dimensions": missing,
        "bindings": request.bindings,
        "reason": reason,
    }

"""Typed request/response contracts for governed NYX explanations."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.resource_lifecycle import VersionReference


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    question: str = Field(min_length=1, max_length=2000)
    selected: VersionReference | None = None
    known_at: datetime | None = None


class ReasonCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference: VersionReference
    display_name: str
    object_type: str
    content_hash: str
    evidence_class: str
    authority_state: str


class ReasonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["nyx-reasoning/1"] = "nyx-reasoning/1"
    state: Literal["EVIDENCE_EXPLANATION", "REFUSED", "NEEDS_EXACT_SCOPE"]
    answer: str
    citations: tuple[ReasonCitation, ...] = ()
    refusal_code: str | None = None
    proposal_handoff: Literal[
        "NOT_AVAILABLE", "REQUIRES_SEPARATE_GOVERNED_PROPOSAL"
    ] = "NOT_AVAILABLE"
    current_use_authorized: bool = False
    business_effect_authorized: bool = False

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.authority import ExactScope


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: ExactScope
    filename: str = Field(min_length=1, max_length=256)
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    requested_objects: tuple[str, ...] = ()
    context_version_id: UUID | None = None
    account_version_ids: dict[str, UUID] = Field(default_factory=dict, max_length=10000)


class CanonicalReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID
    version_id: UUID


class Candidate(BaseModel):
    canonical_references: dict[str, CanonicalReference] = Field(default_factory=dict)
    object_type: str
    source_row: int
    epistemic_state: Literal["OBSERVED", "DERIVED"]
    values: dict[str, str]
    function: str | None = None
    authority_state: Literal["MAPPED_CANDIDATE"] = "MAPPED_CANDIDATE"


class IngestReceipt(BaseModel):
    receipt_id: str
    request_sha256: str
    context_version_id: UUID | None = None
    canonical_references: dict[str, CanonicalReference] = Field(default_factory=dict)
    binding_state: Literal["SOURCE_ONLY", "CANONICAL_BOUND"] = "SOURCE_ONLY"
    source_sha256: str
    scope: ExactScope
    source_class: Literal["TRIAL_BALANCE", "UNFAMILIAR_TABULAR"]
    classifier_version: str = "csv-header-classifier/1"
    classifier_confidence: Literal["STRUCTURAL_ONLY"] = "STRUCTURAL_ONLY"
    authority_contract_version: str
    pack_version: str
    compiler_version: str = "hydration/1"
    plan: tuple[str, ...]
    observed_bindings: dict[str, str]
    inferred_bindings: tuple[str, ...] = ()
    used_fields: tuple[str, ...]
    unused_fields: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    rejects: tuple[str, ...]
    warnings: tuple[str, ...]
    reconciliation: dict[str, str]
    functions_executed: tuple[str, ...]
    deepest_authentic_drill: Literal["SOURCE_ROW"] = "SOURCE_ROW"
    authority_state: Literal["MAPPED_CANDIDATE"] = "MAPPED_CANDIDATE"
    model_version: None = None
    prompt_version: None = None

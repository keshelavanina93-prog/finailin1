from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EpistemicState(StrEnum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    INFERRED = "INFERRED"
    UNAVAILABLE = "UNAVAILABLE"


class SourceKind(StrEnum):
    TRIAL_BALANCE = "TRIAL_BALANCE"
    GENERAL_LEDGER = "GENERAL_LEDGER"
    DATABASE = "DATABASE"
    DOCUMENT = "DOCUMENT"


class ExactScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    legal_entity_id: str = Field(min_length=1, max_length=128)
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=256)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1, max_length=1024)


class SourceField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    source_path: str = Field(min_length=1, max_length=512)
    semantic_type: str | None = Field(default=None, max_length=128)


class SourceAuthorityContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_id: UUID = Field(default_factory=uuid4)
    contract_version: Annotated[int, Field(ge=1)] = 1
    source_kind: SourceKind
    scope: ExactScope
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    observed_fields: tuple[SourceField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_field_names(self) -> SourceAuthorityContract:
        names = [field.name for field in self.observed_fields]
        if len(names) != len(set(names)):
            raise ValueError("observed field names must be unique")
        return self


class DerivationRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    output_field: str = Field(min_length=1, max_length=128)
    rule_id: str = Field(min_length=1, max_length=128)
    rule_version: Annotated[int, Field(ge=1)] = 1
    depends_on: tuple[str, ...] = Field(min_length=1)


class RequestedField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    inference_candidate: bool = False


class CompileHydrationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authority_contract: SourceAuthorityContract
    requested_fields: tuple[RequestedField, ...] = Field(min_length=1)
    derivation_rules: tuple[DerivationRule, ...] = ()
    compiler_version: Literal["authority-compiler/0.1"] = "authority-compiler/0.1"


class FieldAuthority(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    state: EpistemicState
    authoritative: bool
    evidence_ids: tuple[str, ...] = ()
    source_path: str | None = None
    rule_id: str | None = None
    rule_version: int | None = None
    dependencies: tuple[str, ...] = ()
    rationale: str


class ConstructionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: str
    compiler_version: str
    authority_contract_id: UUID
    authority_contract_version: int
    exact_scope: ExactScope
    request_sha256: str
    fields: tuple[FieldAuthority, ...]
    promotion_state: Literal["CANDIDATE_ONLY"] = "CANDIDATE_ONLY"


def canonical_sha256(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", exclude_none=False)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()

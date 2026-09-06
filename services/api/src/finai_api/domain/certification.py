"""Explicit, bounded structural certification; never financial certification."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.ontology_definitions import DEFINITION_MODELS
from finai_api.domain.resource_lifecycle import VersionReference

BOOTSTRAP_TYPES = frozenset({"SchemaDefinition", "SemanticContract", "LinkType"})
SUBJECT_TYPES = frozenset(DEFINITION_MODELS) | BOOTSTRAP_TYPES
Check = Literal["schema compatibility", "identity cycles", "dependency version pins", "impact"]


class CertificationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim: Literal["CANONICAL_DEFINITION_CONFORMANCE"]
    evaluator: Literal["canonical-structural-contract/v1"]
    subject_type: str
    required_checks: list[Check] = Field(min_length=1, max_length=4)
    meaning: str = Field(min_length=10, max_length=2000)
    limitations: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def supported(self) -> "CertificationDefinition":
        if self.subject_type not in SUBJECT_TYPES:
            raise ValueError("Only canonical definition conformance is supported")
        if len(set(self.required_checks)) != len(self.required_checks):
            raise ValueError("Certification checks must be unique")
        return self


class CertificationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    definition: CertificationDefinition
    subject_schema_id: UUID | None = None
    evidence_id: UUID | None = None

    @model_validator(mode="after")
    def schema_required(self) -> "CertificationContract":
        if self.subject_schema_id is None and self.definition.subject_type not in BOOTSTRAP_TYPES:
            raise ValueError("Non-bootstrap subjects require an exact canonical schema dependency")
        return self


class CertificationEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID = Field(default_factory=uuid4)
    subject: VersionReference
    contract: VersionReference

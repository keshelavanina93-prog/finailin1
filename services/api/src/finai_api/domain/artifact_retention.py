"""Exact existing artifact references and reviewed retention conditions."""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.resource_lifecycle import VersionReference

ArtifactClass = Literal[
    "IMMUTABLE_SOURCE_EVIDENCE",
    "AUTHORITATIVE_RECORD",
    "REPRODUCIBLE_DERIVED_ARTIFACT",
    "DISPOSABLE_CACHE_MATERIALIZATION",
]
Action = Literal["PRESERVE", "ARCHIVE", "DELETE"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceReceiptReference(FrozenModel):
    kind: Literal["SOURCE_RECEIPT"]
    receipt_id: str = Field(pattern=r"^ir_[a-f0-9]{64}$")


class SourceDocumentReference(FrozenModel):
    kind: Literal["SOURCE_DOCUMENT"]
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")


class FactRunReference(FrozenModel):
    kind: Literal["FACT_RUN"]
    run_id: str = Field(pattern=r"^fcr_[a-f0-9]{64}$")


class PublicationReference(FrozenModel):
    kind: Literal["PUBLICATION_MANIFEST"]
    workflow_id: str = Field(min_length=1, max_length=256)
    generation: int = Field(ge=0)
    publication_id: str = Field(pattern=r"^pub_[a-f0-9]{64}$")


ArtifactReference = Annotated[
    SourceReceiptReference | SourceDocumentReference | FactRunReference | PublicationReference,
    Field(discriminator="kind"),
]


class RetentionDefinition(FrozenModel):
    artifact_classes: list[ArtifactClass] = Field(min_length=1, max_length=4)
    minimum_retention_days: int = Field(ge=0, le=365000)
    legal_basis_state: Literal["NOT_ESTABLISHED", "DECLARED"]
    legal_basis: str | None = Field(default=None, min_length=10, max_length=2000)
    legal_hold: bool

    @model_validator(mode="after")
    def explicit_basis(self) -> "RetentionDefinition":
        if len(set(self.artifact_classes)) != len(self.artifact_classes):
            raise ValueError("Retention artifact classes must be unique")
        if self.legal_basis_state == "DECLARED" and (
            not self.legal_basis or len(self.legal_basis.strip()) < 10
        ):
            raise ValueError("Declared policy requires an explicit basis")
        return self


class RetentionPolicy(FrozenModel):
    definition: RetentionDefinition
    evidence_id: UUID | None = None


class RetentionEvaluationRequest(FrozenModel):
    request_id: UUID = Field(default_factory=uuid4)
    artifact: ArtifactReference
    policy: VersionReference | None = None
    requested_action: Action = "PRESERVE"

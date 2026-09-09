"""Retained external meaning uses canonical resources, never enterprise identity authority."""

from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from finai_api.domain.semantic_analysis import Pin

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Iri = Annotated[str, StringConstraints(min_length=1, max_length=2048)]
Syntax = Literal["TURTLE", "RDF_XML"]


def absolute_iri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https", "urn"}
        or any(character.isspace() or ord(character) < 32 for character in value)
        or parsed.username
        or parsed.password
        or (parsed.scheme in {"http", "https"} and not parsed.hostname)
        or (parsed.scheme == "urn" and not parsed.path)
    ):
        raise ValueError("An absolute HTTP(S) or URN identifier without credentials is required")
    return value


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetainedDocument(Model):
    document_id: str = Field(pattern=r"^doc_[a-f0-9]{64}$")
    sha256: Digest
    byte_length: int = Field(strict=True, ge=1, le=32_000_000)


class SourceDefinition(Model):
    contract: Literal["external-ontology-source/1"] = "external-ontology-source/1"
    publisher: str = Field(min_length=1, max_length=300)
    source_url: Iri
    namespaces: list[Iri] = Field(min_length=1, max_length=32)
    license: str = Field(min_length=1, max_length=4000)
    supported_formats: list[Syntax] = Field(min_length=1, max_length=2)
    retrieval_policy: Literal["OFFLINE_RETAINED_ONLY"] = "OFFLINE_RETAINED_ONLY"

    _url = field_validator("source_url")(absolute_iri)

    @field_validator("publisher", "license")
    @classmethod
    def substantive(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Publisher and license declarations must be substantive")
        return value

    @field_validator("namespaces")
    @classmethod
    def namespace_identifiers(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Namespace declarations must be unique")
        return [absolute_iri(value) for value in values]


class ModuleInput(Model):
    source: Pin
    artifact_iri: Iri
    document: RetainedDocument
    format: Syntax
    owned_namespaces: list[Iri] = Field(min_length=1, max_length=32)
    permitted_import_iris: list[Iri] = Field(default_factory=list, max_length=16)
    source_url: Iri
    license: str = Field(min_length=1, max_length=4000)
    retrieved_at: datetime

    _url = field_validator("artifact_iri", "source_url")(absolute_iri)

    @field_validator("owned_namespaces", "permitted_import_iris")
    @classmethod
    def identifiers(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("RDF identifiers must be unique")
        return [absolute_iri(value) for value in values]

    @field_validator("retrieved_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Retrieval time must include a timezone")
        return value


class ImportRequest(Model):
    source: Pin
    release_label: str = Field(min_length=1, max_length=128)
    publication_status: Literal["PRODUCTION", "DEVELOPMENT"]
    modules: list[ModuleInput] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def unique_modules(self) -> "ImportRequest":
        if len({module.artifact_iri for module in self.modules}) != len(self.modules):
            raise ValueError("Every module needs a distinct artifact IRI")
        if self.source not in [module.source for module in self.modules]:
            raise ValueError("The release publisher must supply at least one selected module")
        if not self.release_label.strip():
            raise ValueError("A release label is required")
        return self


class ReleaseDefinition(Model):
    contract: Literal["external-ontology-release/1"] = "external-ontology-release/1"
    request: ImportRequest
    canonical_dataset: RetainedDocument
    import_report: RetainedDocument
    request_sha256: Digest
    engine_manifest: dict[str, Any] = Field(max_length=40)
    interpretation: Literal["EXTERNAL_MEANING_ONLY"] = "EXTERNAL_MEANING_ONLY"
    reasoning: Literal["NONE"] = "NONE"
    constraint_validation: Literal["NOT_PERFORMED"] = "NOT_PERFORMED"


class ModuleDefinition(Model):
    contract: Literal["external-ontology-module/1"] = "external-ontology-module/1"
    module: ModuleInput
    graph_iri: Iri

    _iri = field_validator("graph_iri")(absolute_iri)

    @model_validator(mode="after")
    def graph_identity(self) -> "ModuleDefinition":
        if self.graph_iri != self.module.artifact_iri:
            raise ValueError("The derived named graph must identify its exact artifact")
        return self


class ImportRunDefinition(Model):
    contract: Literal["ontology-import-run/1"] = "ontology-import-run/1"
    report: RetainedDocument
    request_sha256: Digest
    outcome: Literal["PARSED_ONLY"] = "PARSED_ONLY"
    business_effect_authorized: Literal[False] = False


class ReleaseInspectionRequest(Model):
    release: Pin
    mode: Literal["CURRENT_RELEASE", "HISTORICAL_INSPECTION"] = "CURRENT_RELEASE"
    known_at: datetime | None = None

    @model_validator(mode="after")
    def inspection_time(self) -> "ReleaseInspectionRequest":
        if self.mode == "HISTORICAL_INSPECTION":
            if self.known_at is None or self.known_at.tzinfo is None:
                raise ValueError("Historical inspection requires an aware knowledge time")
        elif self.known_at is not None:
            raise ValueError("Knowledge time is only supported for historical inspection")
        return self


class TermInspectionRequest(ReleaseInspectionRequest):
    subject_iri: Iri
    limit: int = Field(default=50, strict=True, ge=1, le=100)

    _iri = field_validator("subject_iri")(absolute_iri)


EXTERNAL_TYPES = frozenset(
    {
        "ExternalOntologySource",
        "ExternalOntologyRelease",
        "ExternalOntologyModule",
        "OntologyImportRun",
    }
)

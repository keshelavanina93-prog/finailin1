"""Reviewed external meaning profiles and exact retained validation intent."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from finai_api.domain.external_ontology import (
    Digest,
    Iri,
    Model,
    RetainedDocument,
    absolute_iri,
)
from finai_api.domain.semantic_analysis import Pin

VALIDATION_TYPES = frozenset(
    {"OntologyProfile", "ExternalConstraintProfile", "OntologyValidationReport"}
)


class GraphSelection(Model):
    release: Pin
    graph_iris: tuple[Iri, ...] = Field(min_length=1, max_length=16)

    @field_validator("graph_iris")
    @classmethod
    def exact_graphs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("Selected graphs must be distinct")
        return tuple(sorted(absolute_iri(value) for value in values))


class ValidationSelection(Model):
    mode: Literal["PROFILE_TARGETS", "FILTER_TARGETS", "EXPLICIT_SHAPE_FOCUS"] = "PROFILE_TARGETS"
    focus_iris: tuple[Iri, ...] = Field(default=(), max_length=100)
    shape_iris: tuple[Iri, ...] = Field(default=(), max_length=32)

    @field_validator("focus_iris", "shape_iris")
    @classmethod
    def exact_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("Validation selectors must be distinct")
        return tuple(sorted(absolute_iri(value) for value in values))

    @model_validator(mode="after")
    def explicit_coverage(self) -> "ValidationSelection":
        if self.mode == "PROFILE_TARGETS" and (self.focus_iris or self.shape_iris):
            raise ValueError("Profile target validation cannot silently narrow its coverage")
        if self.mode != "PROFILE_TARGETS" and not self.focus_iris:
            raise ValueError("Selected validation requires explicit focus nodes")
        if self.mode == "EXPLICIT_SHAPE_FOCUS" and not self.shape_iris:
            raise ValueError("Explicit shape/focus evaluation requires selected shapes")
        return self


class OntologyProfileDefinition(Model):
    contract: Literal["external-ontology-profile/1"] = "external-ontology-profile/1"
    purpose: str = Field(min_length=10, max_length=2000)
    domain_pack: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    members: tuple[GraphSelection, ...] = Field(min_length=1, max_length=8)
    compatibility_policy: Literal["EXACT_REVIEWED_PINS"] = "EXACT_REVIEWED_PINS"
    reasoning: Literal["NONE"] = "NONE"
    business_effect_authorized: Literal[False] = False

    @field_validator("purpose")
    @classmethod
    def meaningful_purpose(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("An explicit substantive profile purpose is required")
        return value.strip()

    @model_validator(mode="after")
    def distinct_releases(self) -> "OntologyProfileDefinition":
        if len({member.release.resource_id for member in self.members}) != len(self.members):
            raise ValueError("One profile cannot contain competing versions of one release")
        return self


class ConstraintProfileDefinition(Model):
    contract: Literal["external-constraint-profile/1"] = "external-constraint-profile/1"
    ontology_profile: Pin
    shapes: GraphSelection
    selection: ValidationSelection = Field(default_factory=ValidationSelection)
    validator: Literal["pyshacl/0.40.1-core-offline/1"] = "pyshacl/0.40.1-core-offline/1"
    inference: Literal["NONE"] = "NONE"
    unsupported_constructs: Literal["REFUSE"] = "REFUSE"
    empty_evaluation: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    business_effect_authorized: Literal[False] = False


class ValidationRunRequest(Model):
    request_id: UUID
    constraint_profile: Pin
    data: GraphSelection


class RetainedGraphSelection(GraphSelection):
    canonical_dataset: RetainedDocument


class ValidationPlan(Model):
    contract: Literal["ontology-validation-plan/1"] = "ontology-validation-plan/1"
    request_sha256: Digest
    ontology_profile: Pin
    constraint_profile: Pin
    data: RetainedGraphSelection
    shapes: RetainedGraphSelection
    selection: ValidationSelection
    validator: Literal["pyshacl/0.40.1-core-offline/1"] = "pyshacl/0.40.1-core-offline/1"
    validator_manifest_sha256: Digest
    business_effect_authorized: Literal[False] = False


class ValidationReportDefinition(Model):
    """An observation reference; validity must be established from the retained execution."""

    contract: Literal["ontology-validation-report/1"] = "ontology-validation-report/1"
    workflow_id: str = Field(pattern=r"^ontology-validation:[a-f0-9-]{36}$")
    request_sha256: Digest
    plan_sha256: Digest
    report: RetainedDocument
    outcome: Literal["CONFORMS", "VIOLATES", "NOT_EVALUATED", "REFUSED"]
    business_effect_authorized: Literal[False] = False

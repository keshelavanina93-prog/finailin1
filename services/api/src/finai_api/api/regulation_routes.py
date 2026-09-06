"""Regulatory workspace over the shared reviewed, bitemporal ontology authority."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from finai_api.api.ontology_routes import User
from finai_api.domain.regulation import RegulatoryDefinition, assess_rule
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.security import require_permission
from finai_api.services import regulatory_sources, resources
from finai_api.services.fact_runs import read_run, retain_run
from finai_api.services.regulatory_licence_context import bind_assessment, licence_bindings
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/ontology/regulation", tags=["regulation"])


@router.post("/sources/capture")
def capture_source(principal: User, request: regulatory_sources.Capture):
    return regulatory_sources.capture(principal, request)


@router.post("/sources/proposals")
def publish_source(principal: User, request: regulatory_sources.Publication):
    require_permission(principal, "ontology_propose")
    return regulatory_sources.propose(principal, request)


@router.get("/sources")
def source_publications(principal: User, offset: Annotated[int, Query(ge=0)] = 0):
    rows = resources.list_resources(principal, "SourceRegulatoryPublication", "", offset)
    return {"publications": rows, "next_offset": offset + 100 if len(rows) == 100 else None}


@router.post("/sources/compare")
def compare_sources(principal: User, request: regulatory_sources.Comparison):
    return retain_run(
        principal,
        regulatory_sources.compare(principal, request),
        runtime="regulatory-source-comparison/1",
    )


@router.get("/sources/inspect")
def inspect_source(principal: User, document_id: str):
    metadata, observed = regulatory_sources.inspect(principal, document_id)
    return {
        "document": {"document_id": document_id, "sha256": metadata["source_sha256"]},
        "observation": observed,
        "source_url": f"https://matsne.gov.ge/ka/document/view/{observed['matsne_id']}?publication={observed['publication']}",
    }


class RuleProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=200)
    key: str = Field(min_length=1, max_length=256)
    act_id: UUID
    legal_entity_id: UUID
    licence_id: UUID
    evidence_id: UUID
    definition: RegulatoryDefinition
    rationale: str = Field(min_length=10, max_length=2000)


@router.post("/proposals")
def propose_rule(principal: User, request: RuleProposal):
    require_permission(principal, "ontology_propose")
    entity = resources.get_resource(principal, request.legal_entity_id)["resource"]
    if entity["object_type"] != "LegalEntity":
        raise WorkspaceError(422, "Regulatory scope requires a legal entity")
    # Persist the interpretation now; its legal effective dates are independently evaluated.
    attributes = request.model_dump(mode="json", exclude={"name", "key", "rationale"})
    proposal = ResourceProposal(
        title=request.name,
        rationale=request.rationale,
        access_entity=entity["access_entity"],
        mutations=[
            ResourceMutation(
                object_type="RegulatoryRule",
                identity_key=request.key,
                display_name=request.name,
                attributes=attributes,
                valid_from=datetime.now(UTC),
                evidence_class="SOURCE_BOUND",
            )
        ],
    )
    return resources.propose(principal, proposal)


@router.get("/rules")
def rules(
    principal: User,
    legal_entity_id: UUID,
    activity: Literal["DISTRIBUTION", "TRANSMISSION", "SUPPLY"],
    customer_count: Annotated[int | None, Query(ge=0)] = None,
    at: datetime | None = None,
    known_at: datetime | None = None,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
):
    at, known_at = at or datetime.now(UTC), known_at or datetime.now(UTC)
    if at.tzinfo is None or known_at.tzinfo is None:
        raise WorkspaceError(422, "Assessment timestamps require a timezone")
    entity = resources.get_resource(principal, legal_entity_id)["resource"]
    if entity["object_type"] != "LegalEntity":
        raise WorkspaceError(422, "Regulatory scope requires a legal entity")
    # Registry valid time describes the interpretation's availability, not the legal period.
    page = resources.list_resources(principal, "RegulatoryRule", "", offset, known_at, known_at)
    holders, complete = licence_bindings(principal, legal_entity_id, at, known_at)
    results = []
    for item in page:
        if str(item.attributes["legal_entity_id"]) != str(legal_entity_id):
            continue
        definition = RegulatoryDefinition.model_validate(item.attributes["definition"])
        dependencies = resources.version_references(principal, item.version_id)
        base = assess_rule(definition, at.date(), activity, customer_count)
        assessed = bind_assessment(base.copy(), dependencies, holders, complete)
        blockers = []
        if base["legal_state"] != "CURRENT_EFFECTIVE":
            blockers.append(base["legal_state"])
        if base["applicability"] != "APPLICABLE":
            blockers.append(base["applicability"])
        if assessed["applicability"] not in {"APPLICABLE", base["applicability"]}:
            blockers.append(assessed["applicability"])
        assessed["blocking_reasons"] = blockers
        results.append(
            {
                "resource": item,
                "dependencies": dependencies,
                "assessment": assessed,
            }
        )
    return {
        "rules": results,
        "at": at,
        "known_at": known_at,
        "context_basis": "USER_SUPPLIED_SCENARIO",
        "company": {key: entity[key] for key in ("resource_id", "version_id", "display_name")},
        "accounting_effects_created": False,
        "next_offset": offset + 100 if len(page) == 100 else None,
    }


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legal_entity_id: UUID
    activity: Literal["DISTRIBUTION", "TRANSMISSION", "SUPPLY"]
    customer_count: int | None = Field(default=None, ge=0)
    at: datetime | None = None
    known_at: datetime | None = None


@router.post("/assessments")
def retain_assessment(principal: User, request: AssessmentRequest):
    at, known = request.at or datetime.now(UTC), request.known_at or datetime.now(UTC)
    collected = []
    for offset in range(0, 10000, 100):
        page = rules(
            principal,
            request.legal_entity_id,
            request.activity,
            request.customer_count,
            at,
            known,
            offset,
        )
        collected.extend(page["rules"])
        if page["next_offset"] is None:
            break
    else:
        raise WorkspaceError(422, "Rule population exceeds complete assessment capacity")
    return retain_run(
        principal,
        {
            **page,
            "rules": collected,
            "next_offset": None,
            "contract": "regulatory-assessment/1",
            "coverage": "COMPLETE_AUTHORIZED_RULE_SCAN",
            "assessment_context": request.model_dump(mode="json") | {"at": at, "known_at": known},
            "no_rules_found": not collected,
        },
        runtime="regulatory-applicability/1",
    )


@router.get("/assessments/{run_id}")
def read_assessment(principal: User, run_id: str):
    result = read_run(principal, run_id)
    if result.get("contract") != "regulatory-assessment/1":
        raise WorkspaceError(404, "Regulatory assessment unavailable")
    return result

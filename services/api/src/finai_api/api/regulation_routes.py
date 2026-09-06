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
from finai_api.services import resources
from finai_api.services.regulatory_licence_context import bind_assessment, licence_bindings
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/ontology/regulation", tags=["regulation"])


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
        results.append(
            {
                "resource": item,
                "assessment": bind_assessment(
                    assess_rule(definition, at.date(), activity, customer_count),
                    resources.version_references(principal, item.version_id),
                    holders,
                    complete,
                ),
            }
        )
    return {
        "rules": results,
        "at": at,
        "known_at": known_at,
        "context_basis": "USER_SUPPLIED_SCENARIO",
        "accounting_effects_created": False,
        "next_offset": offset + 100 if len(page) == 100 else None,
    }

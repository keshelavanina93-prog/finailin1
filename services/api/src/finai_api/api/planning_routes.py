"""Exact-scope planning catalog and deterministic comparison endpoints."""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import planning, resources

router = APIRouter(prefix="/v1/ontology/planning", tags=["planning"])
User = Annotated[Principal, Depends(authenticated_principal)]


class ScenarioCellInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_article_id: str = Field(min_length=1, max_length=128)
    period_id: str = Field(min_length=1, max_length=128)
    period_starts_on: date
    period_ends_on: date
    department_id: str = Field(min_length=1, max_length=128)
    measure: Literal["GEL", "M3", "PRICE", "QTY"]
    source_family: str = Field(min_length=1, max_length=128)
    amount: str = Field(pattern=r"^-?\d{1,40}(?:\.\d{1,8})?$")
    currency_id: str = Field(min_length=1, max_length=128)
    scale: int = Field(ge=0, le=18)


class ScenarioProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)
    kind: Literal["BUDGET", "FORECAST", "ADJUSTMENT"]
    valid_from: datetime
    rationale: str = Field(min_length=10, max_length=2000)
    cells: list[ScenarioCellInput] = Field(min_length=1, max_length=100)


@router.get("/catalog")
def catalog(principal: User) -> dict[str, Any]:
    return planning.catalog(principal)


@router.get("/compare")
def compare(principal: User, scenario_a: UUID, scenario_b: UUID) -> dict[str, Any]:
    return planning.compare(principal, scenario_a, scenario_b)


@router.get("/forecast")
def forecast(principal: User, scenario_id: UUID) -> dict[str, Any]:
    return planning.forecast(principal, scenario_id)


@router.get("/liquidity")
def liquidity(principal: User, scenario_id: UUID) -> dict[str, Any]:
    return planning.liquidity(principal, scenario_id)


@router.post("/proposals")
def propose_scenario(principal: User, request: ScenarioProposalRequest) -> dict[str, Any]:
    if "ontology_propose" not in principal.permissions:
        raise planning.WorkspaceError(
            403, "Scenario proposals require ontology proposal permission"
        )
    company_id = principal.scope.legal_entity_id
    scenario_id = uuid4()
    mutations = [
        ResourceMutation(
            resource_id=scenario_id,
            access_entity=company_id,
            object_type="ScenarioVersion",
            identity_key=f"scenario:{company_id}:{request.code}",
            display_name=request.code,
            attributes={"code": request.code, "kind": request.kind},
            valid_from=request.valid_from,
            evidence_class="USER_ASSERTED",
        )
    ]
    for index, cell in enumerate(request.cells):
        mutations.append(
            ResourceMutation(
                access_entity=company_id,
                object_type="PlanningCellFact",
                identity_key=f"planning-cell:{scenario_id}:{index}",
                display_name=f"{request.code} cell {index + 1}",
                attributes={
                    "grain": "PLANNING_CELL",
                    "legal_entity_id": company_id,
                    "scenario_version_id": str(scenario_id),
                    **cell.model_dump(mode="json"),
                },
                valid_from=request.valid_from,
                evidence_class="USER_ASSERTED",
            )
        )
    proposal = ResourceProposal(
        proposal_id=uuid4(),
        title=f"Scenario proposal: {request.code}",
        rationale=request.rationale,
        access_entity=company_id,
        mutations=mutations,
    )
    detail = resources.propose(principal, proposal)
    return {
        "contract": "scenario-proposal/1",
        "proposal": detail.model_dump(mode="json"),
        "scenario_id": str(scenario_id),
        "review_required": True,
    }

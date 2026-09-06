from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_definitions import DEFINITION_MODELS, DefinitionWrite
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceReview
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import ontology_definitions as definitions
from finai_api.services import resources
from finai_api.services.account_ontology import inspect_accounts, propose_accounts
from finai_api.services.fact_aggregation import aggregate_facts
from finai_api.services.fact_reconciliation import reconcile_facts
from finai_api.services.fact_runs import read_run, retain_run
from finai_api.services.guarded_fact_runs import aggregate_guarded

router = APIRouter(prefix="/v1/ontology/model", tags=["ontology model and execution"])
User = Annotated[Principal, Depends(authenticated_principal)]


class AccountPublication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=40, ge=1, le=40)


@router.get("/sources/{receipt_id}/accounts")
def source_accounts(principal: User, receipt_id: str) -> dict[str, Any]:
    return inspect_accounts(principal, receipt_id)


@router.post("/sources/{receipt_id}/accounts/proposal")
def source_account_proposal(principal: User, receipt_id: str, request: AccountPublication) -> Any:
    return propose_accounts(principal, receipt_id, request.offset, request.limit)


class BindingRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: ObjectSetQuery
    rationale: str = Field(min_length=10, max_length=2000)


class DerivedRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: ObjectSetQuery
    definitions: list[UUID] = Field(min_length=1, max_length=20)
    definition_versions: dict[UUID, UUID] = Field(default_factory=dict, max_length=20)


class AggregateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: ObjectSetQuery
    group_by: list[str] = Field(default_factory=list, max_length=20)
    as_of: date | None = None


class ReconcileRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: ObjectSetQuery
    right: ObjectSetQuery
    as_of: date | None = None


class GuardedAggregateRun(AggregateRun):
    consumer: VersionReference


@router.post("/facts/{identity}/aggregate/guarded")
def guarded_aggregate(
    principal: User, identity: UUID, request: GuardedAggregateRun
) -> dict[str, Any]:
    return aggregate_guarded(
        principal, identity, request.consumer, request.query, request.group_by, request.as_of
    )


@router.post("/facts/{identity}/reconcile")
def reconcile(principal: User, identity: UUID, request: ReconcileRun) -> dict[str, Any]:
    return retain_run(
        principal, reconcile_facts(principal, identity, request.left, request.right, request.as_of)
    )


@router.get("/fact-runs/{run_id}")
def calculation_run(principal: User, run_id: str) -> dict[str, Any]:
    return read_run(principal, run_id)


@router.post("/facts/{identity}/aggregate")
def aggregate(principal: User, identity: UUID, request: AggregateRun) -> dict[str, Any]:
    return retain_run(
        principal,
        aggregate_facts(principal, identity, request.query, request.group_by, request.as_of),
    )


@router.get("/definitions")
def list_definitions(
    principal: User, valid_at: datetime | None = None, known_at: datetime | None = None
) -> list[dict[str, Any]]:
    return definitions.definitions(principal, valid_at, known_at)


@router.post("/definitions")
def propose_definition(principal: User, request: DefinitionWrite) -> Any:
    return definitions.propose_definition(principal, request)


@router.post("/definitions/preview")
def preview_definition(principal: User, request: DefinitionWrite) -> Any:
    return definitions.preview_definition(principal, request)


@router.get("/definitions/contracts")
def definition_contracts(principal: User) -> Any:
    return {
        "write": DefinitionWrite.model_json_schema(),
        "kinds": {
            name: model.model_json_schema()
            for name, model in DEFINITION_MODELS.items()
            if name != "RegulatoryRule"
        },
    }


@router.get("/definitions/{identity}")
def get_definition(
    principal: User,
    identity: UUID,
    version: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    return definitions.definition(
        principal, identity, version, valid_at=valid_at, known_at=known_at
    )


@router.post("/proposals/{identity}/decision")
def decide(principal: User, identity: UUID, request: ResourceReview) -> Any:
    return resources.review(principal, identity, request)


@router.get("/sets/{identity}/objects")
def run_set(
    principal: User,
    identity: UUID,
    version: UUID | None = None,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    return definitions.run_set(principal, identity, version, offset, limit, valid_at, known_at)


@router.get("/groups/{identity}/objects")
def run_group(
    principal: User,
    identity: UUID,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    version: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    return definitions.run_group(principal, identity, offset, limit, version, valid_at, known_at)


@router.post("/bindings/{identity}/proposal")
def bind(principal: User, identity: UUID, request: BindingRun) -> Any:
    return definitions.run_binding(principal, identity, request.query, request.rationale)


@router.post("/derived/query")
def derive(principal: User, request: DerivedRun) -> dict[str, Any]:
    return retain_run(
        principal,
        definitions.derive_query(
            principal, request.query, request.definitions, request.definition_versions
        ),
        runtime="ontology-derived/1",
    )

"""Finance ontology publication, evidence intake and deterministic execution."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Path
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from finai_api.domain.finance_candidates import CandidateIntakeRequest
from finai_api.domain.finance_classification import ClassificationRequest
from finai_api.domain.finance_dimensions import DimensionValidationRequest
from finai_api.domain.finance_execution import (
    CanonicalJournalTrialBalanceRequest,
    FinanceExecutionRequest,
)
from finai_api.domain.finance_mapping_registry import MappingRegistryProposalRequest
from finai_api.domain.finance_ontology import CatalogProposalRequest
from finai_api.domain.ontology_definitions import DEFINITION_MODELS
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import (
    finance_candidates,
    finance_classification,
    finance_execution,
    finance_mapping_registry,
)
from finai_api.services import finance_ontology as finance
from finai_api.services.fact_runs import read_run

router = APIRouter(prefix="/v1/ontology/finance", tags=["finance ontology"])
User = Annotated[Principal, Depends(authenticated_principal)]
RunId = Annotated[str, Path(pattern=r"^fcr_[a-f0-9]{64}$")]


@router.get("/catalog")
def catalog(principal: User) -> dict[str, Any]:
    return finance.catalog(principal)


@router.get("/domain")
def domain(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return finance.domain_catalog()


@router.get("/dimensions/policies")
def dimension_policies(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return finance.dimension_policies()


@router.post("/dimensions/validate")
def validate_dimensions(principal: User, request: DimensionValidationRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return finance.validate_dimensions(request)


@router.get("/constructions")
def constructions(principal: User) -> Any:
    require_permission(principal, "ontology_read")
    return finance_candidates.constructions()


@router.get("/functions")
def functions(principal: User) -> dict[str, Any]:
    return finance.functions(principal)


@router.get("/actions")
def actions(principal: User) -> dict[str, Any]:
    return finance.actions(principal)


@router.post("/catalog/proposals")
def propose_catalog(principal: User, request: CatalogProposalRequest) -> Any:
    return finance.propose_catalog(principal, request)


@router.post("/candidates/preview")
def preview_candidates(principal: User, request: CandidateIntakeRequest) -> dict[str, Any]:
    return finance_candidates.preview(principal, request)


@router.post("/candidates/proposals")
def propose_candidates(principal: User, request: CandidateIntakeRequest) -> Any:
    return finance_candidates.submit(principal, request)


@router.post("/mapping-registry/proposals")
def propose_mapping_registry(principal: User, request: MappingRegistryProposalRequest) -> Any:
    proposal = finance_mapping_registry.prepare_mapping_registry_proposal(
        principal,
        registry_id=request.registry_id,
        registry_version=request.registry_version,
        source_family=request.source_family,
        source_hashes=request.source_hashes,
        entries=request.entries,
        rationale=request.rationale,
        valid_from=request.valid_from,
    )
    return finance_mapping_registry.submit_mapping_registry_proposal(principal, proposal)


@router.post("/classify")
def classify(principal: User, request: ClassificationRequest) -> dict[str, Any]:
    return finance_classification.classify(principal, request)


@router.post("/execute")
def execute(principal: User, request: FinanceExecutionRequest) -> dict[str, Any]:
    return finance_execution.execute(principal, request)


@router.post("/journal-trial-balance")
def journal_trial_balance(
    principal: User, request: CanonicalJournalTrialBalanceRequest
) -> dict[str, Any]:
    return finance_execution.execute_journal_trial_balance(principal, request)


@router.get("/runs/{run_id}")
def run(principal: User, run_id: RunId) -> dict[str, Any]:
    return read_run(principal, run_id)


@router.get("/runs/{run_id}/export")
def export_run(principal: User, run_id: RunId) -> JSONResponse:
    require_permission(principal, "export")
    result = read_run(principal, run_id)
    return JSONResponse(
        jsonable_encoder(result),
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/contracts")
def contracts(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    models: dict[str, type[BaseModel]] = {
        "CatalogProposalRequest": CatalogProposalRequest,
        "CandidateIntakeRequest": CandidateIntakeRequest,
        "MappingRegistryProposalRequest": MappingRegistryProposalRequest,
        "ClassificationRequest": ClassificationRequest,
        "FinanceExecutionRequest": FinanceExecutionRequest,
        "CanonicalJournalTrialBalanceRequest": CanonicalJournalTrialBalanceRequest,
        **{name: model for name, model in DEFINITION_MODELS.items() if name.startswith("Finance")},
    }
    return {
        name: cast(type[BaseModel], model).model_json_schema() for name, model in models.items()
    }

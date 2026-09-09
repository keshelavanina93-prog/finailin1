import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from finai_api.api.account_dimension_policy_routes import router as account_dimension_policy_router
from finai_api.api.certification_routes import router as certification_router
from finai_api.api.company_changes_routes import router as company_changes_router
from finai_api.api.company_condition_routes import router as company_condition_router
from finai_api.api.company_context_routes import router as company_context_router
from finai_api.api.company_home_routes import router as company_home_router
from finai_api.api.company_journal_routes import router as company_journal_router
from finai_api.api.event_time_routes import router as event_time_router
from finai_api.api.finance_ontology_routes import router as finance_ontology_router
from finai_api.api.function_routes import router as function_router
from finai_api.api.history_search_routes import router as history_search_router
from finai_api.api.lifecycle_routes import router as lifecycle_router
from finai_api.api.metric_routes import router as metric_router
from finai_api.api.object_set_routes import router as object_set_router
from finai_api.api.ontology_definition_routes import router as ontology_definition_router
from finai_api.api.ontology_import_routes import router as ontology_import_router
from finai_api.api.ontology_operation_routes import router as ontology_operation_router
from finai_api.api.ontology_routes import router as ontology_router
from finai_api.api.operations_routes import router as operations_router
from finai_api.api.operator_routes import router as operator_router
from finai_api.api.period_control_routes import router as period_control_router
from finai_api.api.proposal_queue_routes import router as proposal_queue_router
from finai_api.api.regulation_routes import router as regulation_router
from finai_api.api.reporting_routes import router as reporting_router
from finai_api.api.retained_analysis_routes import router as retained_analysis_router
from finai_api.api.retention_routes import router as retention_router
from finai_api.api.routes import router
from finai_api.api.runtime_observation_routes import router as runtime_observation_router
from finai_api.api.semantic_analysis_routes import router as semantic_analysis_router
from finai_api.api.source_adoption_routes import router as source_adoption_router
from finai_api.api.source_document_routes import router as source_document_router
from finai_api.api.source_exception_routes import router as source_exception_router
from finai_api.api.transformation_routes import router as transformation_router
from finai_api.api.workflow_routes import router as workflow_router
from finai_api.api.workspace_routes import router as workspace_router
from finai_api.evidence_objects import EvidenceStoreUnavailable
from finai_api.services.workspace import WorkspaceError

app = FastAPI(
    title="G8 by NYXCore API",
    summary="Evidence-native enterprise operating platform",
    version="0.1.0",
)
app.include_router(router)
app.include_router(account_dimension_policy_router)
app.include_router(reporting_router)
app.include_router(workspace_router)
app.include_router(workflow_router)
app.include_router(ontology_router)
app.include_router(object_set_router)
app.include_router(ontology_definition_router)
app.include_router(lifecycle_router)
app.include_router(certification_router)
app.include_router(retention_router)
app.include_router(retained_analysis_router)
app.include_router(function_router)
app.include_router(metric_router)
app.include_router(finance_ontology_router)
app.include_router(ontology_import_router)
app.include_router(runtime_observation_router)
app.include_router(semantic_analysis_router)
app.include_router(transformation_router)
app.include_router(event_time_router)
app.include_router(history_search_router)
app.include_router(operations_router)
app.include_router(regulation_router)
app.include_router(operator_router)
app.include_router(proposal_queue_router)
app.include_router(source_document_router)
app.include_router(source_exception_router)
app.include_router(source_adoption_router)
app.include_router(company_context_router)
app.include_router(company_condition_router)
app.include_router(company_changes_router)
app.include_router(company_home_router)
app.include_router(company_journal_router)
app.include_router(period_control_router)
app.include_router(ontology_operation_router)


@app.exception_handler(WorkspaceError)
async def workspace_error(_request: Request, exc: WorkspaceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


@app.exception_handler(psycopg.Error)
async def database_error(_request: Request, exc: psycopg.Error) -> JSONResponse:
    if (
        isinstance(exc, psycopg.errors.RaiseException)
        and exc.diag.message_primary == "Canonical identity type and access boundary are immutable"
    ):
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Canonical identity or access boundary conflict; steward review required"
            },
        )
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return JSONResponse(
            status_code=409,
            content={"detail": "Conflicting request identity; refresh before retrying"},
        )
    return JSONResponse(status_code=503, content={"detail": "Workspace storage is unavailable"})


@app.exception_handler(EvidenceStoreUnavailable)
async def evidence_store_error(_request: Request, _exc: EvidenceStoreUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Retained evidence storage is unavailable or failed integrity verification"
        },
    )

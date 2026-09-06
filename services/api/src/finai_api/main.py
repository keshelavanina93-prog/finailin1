import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from finai_api.api.company_context_routes import router as company_context_router
from finai_api.api.event_time_routes import router as event_time_router
from finai_api.api.history_search_routes import router as history_search_router
from finai_api.api.lifecycle_routes import router as lifecycle_router
from finai_api.api.object_set_routes import router as object_set_router
from finai_api.api.ontology_definition_routes import router as ontology_definition_router
from finai_api.api.ontology_operation_routes import router as ontology_operation_router
from finai_api.api.ontology_routes import router as ontology_router
from finai_api.api.operations_routes import router as operations_router
from finai_api.api.operator_routes import router as operator_router
from finai_api.api.proposal_queue_routes import router as proposal_queue_router
from finai_api.api.regulation_routes import router as regulation_router
from finai_api.api.reporting_routes import router as reporting_router
from finai_api.api.routes import router
from finai_api.api.source_document_routes import router as source_document_router
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
app.include_router(reporting_router)
app.include_router(workspace_router)
app.include_router(workflow_router)
app.include_router(ontology_router)
app.include_router(object_set_router)
app.include_router(ontology_definition_router)
app.include_router(lifecycle_router)
app.include_router(event_time_router)
app.include_router(history_search_router)
app.include_router(operations_router)
app.include_router(regulation_router)
app.include_router(operator_router)
app.include_router(proposal_queue_router)
app.include_router(source_document_router)
app.include_router(company_context_router)
app.include_router(ontology_operation_router)


@app.exception_handler(WorkspaceError)
async def workspace_error(_request: Request, exc: WorkspaceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


@app.exception_handler(psycopg.Error)
async def database_error(_request: Request, exc: psycopg.Error) -> JSONResponse:
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

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from finai_api.api.ontology_routes import router as ontology_router
from finai_api.api.routes import router
from finai_api.api.workspace_routes import router as workspace_router
from finai_api.evidence_objects import EvidenceStoreUnavailable
from finai_api.services.workspace import WorkspaceError

app = FastAPI(
    title="G8 by NYXCore API",
    summary="Evidence-native enterprise operating platform",
    version="0.1.0",
)
app.include_router(router)
app.include_router(workspace_router)
app.include_router(ontology_router)


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

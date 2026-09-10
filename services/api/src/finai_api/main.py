import os
import subprocess
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from finai_api.api.account_dimension_policy_routes import router as account_dimension_policy_router
from finai_api.api.certification_routes import router as certification_router
from finai_api.api.company_changes_routes import router as company_changes_router
from finai_api.api.company_condition_routes import router as company_condition_router
from finai_api.api.company_context_routes import router as company_context_router
from finai_api.api.company_financial_result_routes import router as company_financial_result_router
from finai_api.api.company_home_routes import router as company_home_router
from finai_api.api.company_journal_routes import router as company_journal_router
from finai_api.api.diagnostic_routes import router as diagnostic_router
from finai_api.api.enterprise_diagnostics_routes import router as enterprise_diagnostics_router
from finai_api.api.event_time_routes import router as event_time_router
from finai_api.api.finance_ontology_routes import router as finance_ontology_router
from finai_api.api.function_routes import router as function_router
from finai_api.api.history_search_routes import router as history_search_router
from finai_api.api.lifecycle_routes import router as lifecycle_router
from finai_api.api.local_auth_routes import router as local_auth_router
from finai_api.api.metric_routes import router as metric_router
from finai_api.api.nyx_reasoning_routes import router as nyx_reasoning_router
from finai_api.api.object_set_routes import router as object_set_router
from finai_api.api.ontology_definition_routes import router as ontology_definition_router
from finai_api.api.ontology_import_routes import router as ontology_import_router
from finai_api.api.ontology_install_routes import router as ontology_install_router
from finai_api.api.ontology_operation_routes import router as ontology_operation_router
from finai_api.api.ontology_routes import router as ontology_router
from finai_api.api.operations_routes import router as operations_router
from finai_api.api.operator_routes import router as operator_router
from finai_api.api.outcome_routes import router as outcome_router
from finai_api.api.period_control_routes import router as period_control_router
from finai_api.api.planning_routes import router as planning_router
from finai_api.api.proposal_queue_routes import router as proposal_queue_router
from finai_api.api.regulation_routes import router as regulation_router
from finai_api.api.reporting_routes import retained_router
from finai_api.api.reporting_routes import router as reporting_router
from finai_api.api.retained_analysis_routes import router as retained_analysis_router
from finai_api.api.retention_routes import router as retention_router
from finai_api.api.routes import router
from finai_api.api.runtime_observation_routes import router as runtime_observation_router
from finai_api.api.semantic_analysis_routes import router as semantic_analysis_router
from finai_api.api.source_adoption_routes import router as source_adoption_router
from finai_api.api.source_document_routes import router as source_document_router
from finai_api.api.source_exception_routes import router as source_exception_router
from finai_api.api.tb_finance_contract_routes import router as tb_finance_contract_router
from finai_api.api.tb_finance_routes import router as tb_finance_router
from finai_api.api.transformation_routes import router as transformation_router
from finai_api.api.trial_balance_package_routes import router as trial_balance_package_router
from finai_api.api.workflow_routes import router as workflow_router
from finai_api.api.workspace_routes import router as workspace_router
from finai_api.evidence_objects import EvidenceStoreUnavailable
from finai_api.services.workspace import WorkspaceError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8061
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

# Keep the API surface explicit.  This is the single composition registry for
# every mounted G8 domain; the local supervisor starts the other runtime
# processes (web, storage, Temporal and worker) around this application.
API_ROUTERS = (
    router,
    account_dimension_policy_router,
    reporting_router,
    retained_router,
    workspace_router,
    workflow_router,
    ontology_router,
    object_set_router,
    ontology_definition_router,
    lifecycle_router,
    local_auth_router,
    certification_router,
    retention_router,
    retained_analysis_router,
    function_router,
    metric_router,
    ontology_import_router,
    runtime_observation_router,
    semantic_analysis_router,
    transformation_router,
    trial_balance_package_router,
    event_time_router,
    finance_ontology_router,
    enterprise_diagnostics_router,
    ontology_install_router,
    history_search_router,
    operations_router,
    regulation_router,
    operator_router,
    proposal_queue_router,
    source_document_router,
    source_exception_router,
    source_adoption_router,
    company_context_router,
    company_condition_router,
    company_financial_result_router,
    company_changes_router,
    company_home_router,
    company_journal_router,
    tb_finance_contract_router,
    tb_finance_router,
    diagnostic_router,
    period_control_router,
    planning_router,
    outcome_router,
    ontology_operation_router,
    nyx_reasoning_router,
)


def create_app() -> FastAPI:
    """Build the complete G8 API application from one router registry."""

    application = FastAPI(
        title="G8 by NYXCore API",
        summary="Evidence-native enterprise operating platform",
        version="0.1.0",
    )
    for mounted_router in API_ROUTERS:
        application.include_router(mounted_router)
    return application

app = create_app()


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


def run_local_stack(api_port: int, web_port: int, postgres_bin: str) -> None:
    """Start the complete local G8 runtime through the canonical supervisor.

    ``main.py`` remains safe for the API supervisor because only the explicit
    ``--stack`` mode delegates to PowerShell.  The supervisor then launches
    this module again without ``--stack`` for the API process.
    """

    if os.name != "nt":
        raise SystemExit("The local full-stack launcher requires Windows PowerShell 7.")
    launcher = REPOSITORY_ROOT / "scripts" / "start-nyxcore-local.ps1"
    if not launcher.is_file():
        raise SystemExit(f"Local stack launcher is missing: {launcher}")
    command = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher),
        "-ApiPort",
        str(api_port),
        "-WebPort",
        str(web_port),
        "-PostgresBin",
        postgres_bin,
    ]
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)


def run() -> None:
    """Run this API composition root as a standalone local process.

    The complete G8 local product is supervised by ``g8-system.ps1``. This
    entrypoint is the API process used by that supervisor, packaging, and
    direct local development, so those paths all execute the same app object.
    """
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the G8 by NYXCore API")
    parser.add_argument(
        "--stack",
        action="store_true",
        help="Start the complete local G8 stack: PostgreSQL, MinIO, Temporal, worker, API and web",
    )
    parser.add_argument("--host", default=os.environ.get("FINAI_API_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("FINAI_API_PORT", DEFAULT_PORT))
    )
    parser.add_argument(
        "--web-port", type=int, default=int(os.environ.get("FINAI_WEB_PORT", 3061))
    )
    parser.add_argument(
        "--postgres-bin",
        default=os.environ.get("FINAI_POSTGRES_BIN", r"D:\PG18\pgsql\bin"),
        help="PostgreSQL bin directory used by --stack",
    )
    args = parser.parse_args()
    for name, value in (("FINAI_API_PORT", args.port), ("FINAI_WEB_PORT", args.web_port)):
        if not 1024 <= value <= 65535:
            raise SystemExit(f"{name} must be between 1024 and 65535, got {value}")
    if args.stack:
        run_local_stack(args.port, args.web_port, args.postgres_bin)
        return
    host = args.host
    port = args.port
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()

"""Mounted generic ACCOUNT_PERIOD TB Finance draft routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import fact_runs, tb_finance_draft
from finai_api.services.tb_reconciliation import reconcile_retained_tb
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/ontology/finance/tb", tags=["TB Finance draft"])
User = Annotated[Principal, Depends(authenticated_principal)]


class TBDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_ids: list[str] = Field(default_factory=list, max_length=tb_finance_draft.MAX_RECEIPTS)
    working_period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    chartpack_id: str = Field(default="chartpack.1c_ge_statutory.v1", max_length=128)


class TBRunRequest(TBDraftRequest):
    run_id: str | None = Field(default=None, pattern=r"^fcr_[a-f0-9]{64}$")


class TBCommandRequest(TBDraftRequest):
    command: str = Field(min_length=3, max_length=100)


@router.get("/sources")
def sources(principal: User) -> list[dict[str, Any]]:
    require_permission(principal, "ontology_read")
    return tb_finance_draft.list_retained_tb_sources(principal)


@router.get("/reconciliation")
def reconciliation(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return reconcile_retained_tb(principal)


@router.get("/contract")
def contract(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    from finai_api.services.tb_finance_contract import contract_definition

    return {
        **contract_definition(),
        "function": tb_finance_draft.TB_DRAFT_FUNCTION,
        "profile": "account_period_tb_finance",
        "period_authority": "SOURCE_INTERNAL_HEADER_ONLY",
        "ingestion_time_policy": "RETAINED_SOURCE_INTAKE_METADATA_ONLY",
    }


@router.post("/draft")
def draft(principal: User, request: TBDraftRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return tb_finance_draft.build_draft(
        principal,
        request.receipt_ids,
        working_period=request.working_period,
        chartpack_id=request.chartpack_id,
    )


@router.get("/runs/{run_id}")
def run(principal: User, run_id: str) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return fact_runs.read_run(principal, run_id)


@router.post("/export")
def export(principal: User, request: TBRunRequest) -> Response:
    require_permission(principal, "export")
    payload = (
        fact_runs.read_run(principal, request.run_id)
        if request.run_id
        else tb_finance_draft.build_draft(
            principal,
            request.receipt_ids,
            working_period=request.working_period,
            chartpack_id=request.chartpack_id,
        )
    )
    content = tb_finance_draft.export_zip(payload)
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="TB_Finance_Draft.zip"',
            "Cache-Control": "no-store",
            "X-FinAI-Certification": "NOT_CERTIFIED",
        },
    )


@router.post("/command")
def command(principal: User, request: TBCommandRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    normalized = " ".join(request.command.casefold().split())
    allowed: dict[str, str] = {
        "show monthly pulse": "year_pulse",
        "show continuity breaks": "continuity",
        "show revenue vs cogs by month": "pnl_draft",
        "show site vs counterparty receivables": "receivables_by_analytic",
        "why is finance a draft": "review",
    }
    key = allowed.get(normalized)
    if key is None:
        raise WorkspaceError(
            422,
            "NYX_COMMAND_REFUSED: TB Finance supports only monthly pulse, continuity breaks, "
            "revenue vs cogs, site vs counterparty receivables, and draft explanation.",
        )
    payload = tb_finance_draft.build_draft(
        principal,
        request.receipt_ids,
        working_period=request.working_period,
        chartpack_id=request.chartpack_id,
    )
    return {
        "command": normalized,
        "result": payload[key],
        "certification": "NOT_CERTIFIED",
        "unit": "source_amount",
    }


@router.get("/diagnostics")
def diagnostics(principal: User) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return {
        "tb_finance_draft": "mounted",
        "profile": "account_period_tb_finance",
        "function": tb_finance_draft.TB_DRAFT_FUNCTION,
        "petroleum_actuals": "unimplemented",
        "company_facts_published": False,
        "certification": "NOT_CERTIFIED",
        "unsupported": ["journals", "liters", "aging", "product_margin", "live_map"],
    }

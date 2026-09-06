from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from finai_api.api.ontology_routes import User
from finai_api.security import require_permission
from finai_api.services import (
    source_account_binding,
    source_accounting_reconciliation,
    source_financial_facts,
)
from finai_api.services.company_source import inspect_companies, propose_companies
from finai_api.services.source_document_preview import preview
from finai_api.services.source_documents import document_bytes, list_documents, retain_document
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/ontology/source-documents", tags=["retained source documents"])


class CompanyColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["company_column", "1c_tb_title"] = "company_column"
    sheet: str = Field(min_length=1, max_length=128)
    header_row: int = Field(default=1, ge=1, le=100000)
    column: int = Field(default=1, ge=1, le=256)


class AccountSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str = Field(min_length=1, max_length=128)
    profile: Literal["1c_tb", "1c_journal"]


class AccountBinding(AccountSource):
    company_id: UUID
    offset: int = Field(default=0, ge=0, le=10000)


@router.post("/{identity}/facts/inspect")
def inspect_facts(principal: User, identity: str, request: AccountBinding):
    return source_financial_facts.prepare(
        principal, identity, request.sheet, request.profile, request.company_id, request.offset
    )


@router.post("/{identity}/facts/reconcile")
def reconcile_facts(principal: User, identity: str, request: AccountBinding):
    return source_accounting_reconciliation.assess(
        principal, identity, request.sheet, request.profile, request.company_id
    )


@router.post("/{identity}/facts/proposal")
def propose_facts(principal: User, identity: str, request: AccountBinding):
    require_permission(principal, "ontology_propose")
    return source_financial_facts.propose(
        principal, identity, request.sheet, request.profile, request.company_id, request.offset
    )


@router.post("/{identity}/accounts/inspect")
def inspect_accounts(principal: User, identity: str, request: AccountSource):
    return source_account_binding.inspect(principal, identity, request.sheet, request.profile)


@router.post("/{identity}/accounts/proposal")
def propose_accounts(principal: User, identity: str, request: AccountBinding):
    require_permission(principal, "ontology_propose")
    return source_account_binding.propose(
        principal, identity, request.sheet, request.profile, request.company_id, request.offset
    )


@router.get("")
def inventory(principal: User, offset: Annotated[int, Query(ge=0)] = 0):
    return list_documents(principal, offset)


@router.post("")
async def upload(
    principal: User, request: Request, filename: Annotated[str, Query(min_length=1, max_length=256)]
):
    require_permission(principal, "ingest")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 32_000_000:
            raise WorkspaceError(413, "Document exceeds 32 MB")
        content.extend(chunk)
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(retain_document, principal, filename, bytes(content))


@router.get("/{identity}/content")
def download(principal: User, identity: str):
    require_permission(principal, "export")
    metadata, content = document_bytes(principal, identity)
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="retained-source.bin"',
            "X-Source-SHA256": metadata["source_sha256"],
            "Cache-Control": "no-store",
        },
    )


@router.get("/{identity}/preview")
def source_preview(
    principal: User,
    identity: str,
    sheet: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
):
    return preview(principal, identity, sheet, offset)


@router.post("/{identity}/companies/inspect")
def inspect(principal: User, identity: str, request: CompanyColumn):
    return inspect_companies(
        principal, identity, request.sheet, request.header_row, request.column, request.mode
    )


@router.post("/{identity}/companies/proposal")
def propose(principal: User, identity: str, request: CompanyColumn):
    require_permission(principal, "ontology_propose")
    return propose_companies(
        principal, identity, request.sheet, request.header_row, request.column, request.mode
    )

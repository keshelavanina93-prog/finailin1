from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from finai_api.api.ontology_routes import User
from finai_api.security import require_permission
from finai_api.services import (
    corporate_disclosures,
    licence_notices,
    source_account_binding,
    source_accounting_context,
    source_accounting_reconciliation,
    source_dimensions,
    source_financial_facts,
)
from finai_api.services.company_source import inspect_companies, propose_companies
from finai_api.services.source_document_preview import preview
from finai_api.services.source_documents import document_bytes, list_documents, retain_document
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/ontology/source-documents", tags=["retained source documents"])


@router.post("/{identity}/licence/inspect")
def inspect_licence_notice(principal: User, identity: str):
    return licence_notices.inspect(principal, identity)


@router.post("/{identity}/licence/proposal")
def propose_licence_notice(
    principal: User, identity: str, request: licence_notices.NoticeSelection
):
    require_permission(principal, "ontology_propose")
    return licence_notices.propose(principal, identity, request)


@router.post("/{identity}/corporate/inspect")
def inspect_corporate_disclosure(principal: User, identity: str):
    return corporate_disclosures.inspect(principal, identity)


@router.post("/{identity}/corporate/proposal")
def propose_corporate_disclosure(
    principal: User, identity: str, request: corporate_disclosures.DisclosureContext
):
    require_permission(principal, "ontology_propose")
    return corporate_disclosures.propose(principal, identity, request)


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


class SourceContextRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str = Field(min_length=1, max_length=128)
    profile: Literal["1c_tb", "1c_journal", "seg_expense_base"]
    company_id: UUID
    offset: int = Field(default=0, ge=0, le=10000)


class SourceContextWrite(SourceContextRead):
    selection: source_accounting_context.ContextSelection


class SourceCompanyBindingWrite(SourceContextRead):
    rationale: str = Field(min_length=10, max_length=2000)


@router.post("/{identity}/accounting-context/company-binding-proposal")
def propose_source_company_binding(
    principal: User, identity: str, request: SourceCompanyBindingWrite
):
    from finai_api.services import source_company_alias

    require_permission(principal, "ontology_propose")
    return source_company_alias.propose(
        principal, identity, request.sheet, request.profile, request.company_id, request.rationale
    )


@router.post("/{identity}/accounting-context/observations")
def accounting_observations(principal: User, identity: str, request: SourceContextRead):
    return source_accounting_context.source_observations(
        principal, identity, request.sheet, request.profile
    )


@router.post("/{identity}/accounting-context/account-observations")
def accounting_account_observations(principal: User, identity: str, request: SourceContextRead):
    from finai_api.services import seg_account_observations

    return seg_account_observations.inspect(
        principal, identity, request.sheet, request.profile, request.company_id
    )


@router.post("/{identity}/accounting-context/inspect")
def inspect_accounting_context(principal: User, identity: str, request: SourceContextRead):
    return source_accounting_context.inspect(
        principal, identity, request.sheet, request.profile, request.company_id
    )


@router.post("/{identity}/accounting-context/scope-proposal")
def propose_source_scope(principal: User, identity: str, request: SourceContextRead):
    require_permission(principal, "ontology_propose")
    return source_accounting_context.propose_scope(
        principal, identity, request.sheet, request.profile, request.company_id
    )


@router.post("/{identity}/accounting-context/binding-proposal")
def propose_source_context(principal: User, identity: str, request: SourceContextWrite):
    require_permission(principal, "ontology_propose")
    return source_accounting_context.propose_binding(
        principal, identity, request.sheet, request.profile, request.company_id, request.selection
    )


class DimensionQuery(AccountBinding):
    member_id: UUID
    valid_at: datetime | None = None
    known_at: datetime | None = None

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Query snapshot timestamps must include a timezone")
        return value


@router.post("/{identity}/dimensions/query")
def dimension_movements(principal: User, identity: str, request: DimensionQuery):
    if request.profile != "1c_journal":
        raise WorkspaceError(422, "This binding requires explicit journal analytical columns")
    return source_dimensions.movements(
        principal,
        identity,
        request.sheet,
        request.company_id,
        request.member_id,
        request.offset,
        request.valid_at,
        request.known_at,
    )


@router.post("/{identity}/dimensions/inspect")
def inspect_dimensions(principal: User, identity: str, request: AccountBinding):
    if request.profile != "1c_journal":
        raise WorkspaceError(422, "This binding requires explicit journal analytical columns")
    result = source_dimensions.inspect(
        principal, identity, request.sheet, request.company_id, request.offset
    )
    return {k: v for k, v in result.items() if k not in {"mutations", "source_versions"}}


@router.post("/{identity}/dimensions/proposal")
def propose_dimensions(principal: User, identity: str, request: AccountBinding):
    require_permission(principal, "ontology_propose")
    if request.profile != "1c_journal":
        raise WorkspaceError(422, "This binding requires explicit journal analytical columns")
    return source_dimensions.propose(
        principal, identity, request.sheet, request.company_id, request.offset
    )


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

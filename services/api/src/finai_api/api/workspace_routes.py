import base64
import json
from hashlib import sha256
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response

from finai_api.domain.review import (
    IntakeItem,
    ObjectDetail,
    Principal,
    ReceiptDetail,
    ReviewDecision,
    ReviewRequest,
    WorkspaceObject,
    WorkspaceSummary,
)
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import source_preview, workbook_source, workspace, xls_source
from finai_api.services.report_inputs import ReportInputRequest, assessments, retain_assessment

router = APIRouter(prefix="/v1/workspace", tags=["operator workspace"])


def reader(principal: Annotated[Principal, Depends(authenticated_principal)]) -> Principal:
    require_permission(principal, "read")
    return principal


User = Annotated[Principal, Depends(reader)]


@router.post("/report-inputs")
def report_input_assessment(request: ReportInputRequest, principal: User) -> dict[str, Any]:
    require_permission(principal, "ingest")
    return retain_assessment(principal, request)


@router.get("/report-inputs")
def report_input_history(principal: User) -> list[dict[str, Any]]:
    return assessments(principal)


@router.get("/session", response_model=Principal)
def session(principal: User) -> Principal:
    return principal


@router.get("/summary", response_model=WorkspaceSummary)
def summary(principal: User) -> WorkspaceSummary:
    return workspace.summary(principal)


@router.get("/intake", response_model=list[IntakeItem])
def intake(
    principal: User,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    state: Literal["PENDING", "APPROVED", "REJECTED"] | None = None,
) -> list[IntakeItem]:
    return workspace.list_intake(principal, offset, state)


@router.get("/constructions/{receipt_id}", response_model=ReceiptDetail)
def construction(receipt_id: str, principal: User) -> ReceiptDetail:
    return workspace.detail(principal, receipt_id)


@router.post("/constructions/{receipt_id}/decision", response_model=ReviewDecision)
def review(receipt_id: str, request: ReviewRequest, principal: User) -> ReviewDecision:
    require_permission(principal, "review")
    return workspace.decide(principal, receipt_id, request)


@router.get("/objects", response_model=list[WorkspaceObject])
def objects(
    principal: User,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    object_type: Literal["Account", "PeriodBalance", "SourceRecord"] | None = None,
    search: Annotated[str, Query(max_length=128)] = "",
    receipt_id: Annotated[str | None, Query(max_length=128)] = None,
) -> list[WorkspaceObject]:
    return workspace.objects(principal, offset, object_type, search, receipt_id)


@router.get("/objects/{object_id}", response_model=ObjectDetail)
def object_detail(object_id: str, principal: User) -> ObjectDetail:
    return workspace.object_detail(principal, object_id)


@router.get("/constructions/{receipt_id}/preview")
def preview_source(
    receipt_id: str,
    principal: User,
    response: Response,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    search: Annotated[str, Query(max_length=128)] = "",
) -> dict[str, Any]:
    # Browsing original cells has the same permission as downloading the original.
    require_permission(principal, "export")
    response.headers["Cache-Control"] = "no-store"
    content = workspace.source_bytes(principal, receipt_id)
    if content.startswith(b"PK\x03\x04"):
        return workbook_source.preview_workbook(content, offset, search)
    if content.startswith(xls_source.SIGNATURE):
        return xls_source.preview_xls(content, offset, search)
    return source_preview.preview(content, offset, search)


@router.get("/constructions/{receipt_id}/source")
def source(receipt_id: str, principal: User) -> Response:
    require_permission(principal, "export")
    content = workspace.source_bytes(principal, receipt_id)
    is_xls = content.startswith(xls_source.SIGNATURE)
    if content.startswith(b"PK\x03\x04"):
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="retained-source.xlsx"',
                "Cache-Control": "no-store",
            },
        )
    return Response(
        content,
        media_type="application/vnd.ms-excel" if is_xls else "text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="retained-source.xls"'
            if is_xls
            else 'attachment; filename="retained-source.csv"',
            "Cache-Control": "no-store",
            "X-Content-SHA256": sha256(content).hexdigest(),
        },
    )


@router.get("/constructions/{receipt_id}/export")
def export(receipt_id: str, principal: User) -> Response:
    require_permission(principal, "export")
    construction = workspace.detail(principal, receipt_id)
    source_content = workspace.source_bytes(principal, receipt_id)
    source_payload = (
        {
            "source_base64": base64.b64encode(source_content).decode("ascii"),
            "source_encoding": "OOXML_XLSX"
            if source_content.startswith(b"PK\x03\x04")
            else "BIFF_XLS",
        }
        if source_content.startswith((xls_source.SIGNATURE, b"PK\x03\x04"))
        else {"source_utf8": source_content.decode("utf-8")}
    )
    bundle = {
        "format": "finai-evidence-bundle/1",
        "scope": principal.scope.model_dump(mode="json"),
        "construction": construction.model_dump(mode="json"),
        **source_payload,
        "certification": "NOT_CERTIFIED",
        "exported_by": principal.actor_id,
    }
    content = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    return Response(
        content,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="finai-evidence-bundle.json"',
            "Cache-Control": "no-store",
            "X-Content-SHA256": sha256(content).hexdigest(),
        },
    )

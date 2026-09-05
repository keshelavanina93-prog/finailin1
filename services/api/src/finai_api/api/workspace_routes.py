import json
from hashlib import sha256
from typing import Annotated, Literal

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
from finai_api.services import workspace

router = APIRouter(prefix="/v1/workspace", tags=["operator workspace"])


def reader(principal: Annotated[Principal, Depends(authenticated_principal)]) -> Principal:
    require_permission(principal, "read")
    return principal


User = Annotated[Principal, Depends(reader)]


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


@router.get("/constructions/{receipt_id}/source")
def source(receipt_id: str, principal: User) -> Response:
    require_permission(principal, "export")
    content = workspace.source_bytes(principal, receipt_id)
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="retained-source.csv"',
            "Cache-Control": "no-store",
            "X-Content-SHA256": sha256(content).hexdigest(),
        },
    )


@router.get("/constructions/{receipt_id}/export")
def export(receipt_id: str, principal: User) -> Response:
    require_permission(principal, "export")
    construction = workspace.detail(principal, receipt_id)
    bundle = {
        "format": "finai-evidence-bundle/1",
        "scope": principal.scope.model_dump(mode="json"),
        "construction": construction.model_dump(mode="json"),
        "source_utf8": workspace.source_bytes(principal, receipt_id).decode("utf-8"),
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

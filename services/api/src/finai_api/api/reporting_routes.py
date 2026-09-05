"""Persisted, source-bound report reconstruction and dependency inspection."""

import json
from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import workspace
from finai_api.services.petroleum_reporting import reconstruct
from finai_api.services.report_export import operating_workbook
from finai_api.storage import connection

router = APIRouter(prefix="/v1/workspace/report-calculations", tags=["report calculations"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.get("/{calculation_id}/export")
def export(calculation_id: str, principal: User) -> Response:
    return Response(
        operating_workbook(saved(calculation_id, principal)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="Operating-PL-reference.xlsx"',
            "Cache-Control": "no-store",
        },
    )


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")


@router.post("")
def calculate(request: CalculationRequest, principal: User) -> dict[str, Any]:
    require_permission(principal, "read")
    require_permission(principal, "ingest")
    # Calculations reveal source amounts, so preserve the source-preview permission gate.
    require_permission(principal, "export")
    detail = workspace.detail(principal, request.receipt_id)
    try:
        result = reconstruct(workspace.source_bytes(principal, request.receipt_id))
    except ValueError as exc:
        raise workspace.WorkspaceError(422, str(exc)) from exc
    scope = principal.scope.model_dump(mode="json")
    result.update({"scope": scope, "receipt_id": request.receipt_id, "filename": detail.filename})
    identity = "rpc_" + sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    result["calculation_id"] = identity
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        conn.execute(
            "INSERT INTO report_source_assessments "
            "(tenant_id,assessment_id,exact_scope,payload,actor_id) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (principal.scope.tenant_id, identity, Jsonb(scope), Jsonb(result), principal.actor_id),
        )
    return result


@router.get("/{calculation_id}")
def saved(calculation_id: str, principal: User) -> dict[str, Any]:
    require_permission(principal, "read")
    require_permission(principal, "export")
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        row = conn.execute(
            "SELECT payload FROM report_source_assessments WHERE tenant_id=%s "
            "AND exact_scope=%s AND assessment_id=%s AND assessment_id LIKE 'rpc_%%'",
            (principal.scope.tenant_id, Jsonb(scope), calculation_id),
        ).fetchone()
        if not row:
            raise workspace.WorkspaceError(404, "Calculation unavailable in authorized scope")
        return dict(row[0])

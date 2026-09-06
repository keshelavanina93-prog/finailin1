"""Read projection of shared workflow requests; no new action or company authority."""

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import report_workflows as records
from finai_api.services import resources


def summarize(identity: str, payload: dict[str, Any], created_at: str) -> dict[str, Any]:
    version = payload.get("definition", {}).get("version", "")
    company = None
    if version == "ontology-action/1":
        family = "ontology"
        title = payload.get("prepared_proposal", {}).get("title", "Review business change")
        company = payload.get("invocation", {}).get("company_id")
    elif version == "regulatory-source-monitor/1":
        family, title = "monitor", payload.get("name", "Regulatory source monitoring")
    else:
        family = "source" if version.startswith("report-source-process/") else "unsupported"
        report = payload.get("report", {})
        title = f"Source assessment · {report.get('company_label', 'Retained request')}"
    return {"workflow_id": identity, "family": family, "title": title,
            "company_id": company, "created_at": created_at,
            "period": payload.get("report", {}).get("period"),
            "currency": payload.get("report", {}).get("currency"),
            "company_binding": "EXPLICIT_INVOCATION" if company else "UNBOUND"}


def listing(principal: Principal, company_id: UUID | None, include_unbound: bool) -> dict[str, Any]:
    require_permission(principal, "read")
    if company_id:
        require_permission(principal, "ontology_read")
        resources.get_resource(principal, company_id)
    with records.scope_connection(principal) as conn:
        scope = records.set_scope(conn, principal)
        rows = conn.execute(
            "SELECT workflow_id,payload,created_at FROM workflow_requests "
            "WHERE tenant_id=%s AND exact_scope=%s "
            "AND (%s::text IS NULL OR payload->'invocation'->>'company_id'=%s "
            "OR (%s AND payload->'invocation'->>'company_id' IS NULL)) "
            "AND (%s OR definition_version<>'ontology-action/1') "
            "ORDER BY created_at DESC,workflow_id LIMIT 101",
            (principal.scope.tenant_id, Jsonb(scope), str(company_id) if company_id else None,
             str(company_id) if company_id else None, include_unbound,
             "ontology_read" in principal.permissions),
        ).fetchall()
    return {"items": [summarize(r[0], r[1], r[2].isoformat()) for r in rows[:100]],
            "truncated": len(rows) > 100, "scope": scope}

"""Bounded discovery of immutable build evidence; live runtime is a separate read."""

from datetime import datetime
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import report_workflows as records
from finai_api.services import transformation_runs
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def discover(
    principal: Principal,
    limit: int = 20,
    before_created_at: datetime | None = None,
    before_request_id: UUID | None = None,
) -> dict:
    require_permission(principal, "ontology_read")
    if not 1 <= limit <= 50 or isinstance(limit, bool):
        raise WorkspaceError(422, "Build history page size must be between 1 and 50")
    if (before_created_at is None) != (before_request_id is None):
        raise WorkspaceError(422, "Build history requires both cursor fields")
    if before_created_at and (
        before_created_at.tzinfo is None or before_created_at.utcoffset() is None
    ):
        raise WorkspaceError(422, "Build history cursor must include a timezone")
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        scope = records.set_scope(conn, principal)
        rows = cursor.execute(
            "SELECT w.workflow_id,w.created_at,"
            "w.payload->'compiled_plan'->'request'->'transformation' AS transformation "
            "FROM workflow_requests w "
            "WHERE w.tenant_id=%s AND w.exact_scope=%s AND w.definition_version=%s "
            "AND (%s::timestamptz IS NULL OR (w.created_at,w.workflow_id)<(%s,%s)) "
            "ORDER BY w.created_at DESC,w.workflow_id DESC LIMIT %s",
            (
                principal.scope.tenant_id,
                Jsonb(scope),
                transformation_runs.VERSION,
                before_created_at,
                before_created_at,
                f"transformation:{before_request_id}" if before_request_id else None,
                limit + 1,
            ),
        ).fetchall()
        # Bound name resolution before touching the version table. A join here can
        # evaluate resource visibility across the entire version history even when
        # only one small workflow page was requested. Exact point reads retain RLS
        # and the historical label; all immutable proof checks still run below.
        for row in rows[:limit]:
            reference = row["transformation"]
            name = cursor.execute(
                "SELECT display_name FROM resource_versions "
                "WHERE tenant_id=%s AND resource_id=%s AND version_id=%s",
                (principal.scope.tenant_id, reference["resource_id"], reference["version_id"]),
            ).fetchone()
            row["display_name"] = name["display_name"] if name else None
    page = rows[:limit]
    items = []
    for row in page:
        # Reuse the existing immutable proof checks rather than projecting an unchecked manifest.
        retained = transformation_runs.read(principal, row["workflow_id"])
        compiled = retained["request"]["compiled_plan"]
        request = compiled["request"]
        terminals = {
            event["event_id"]: event
            for event in retained["events"]
            if event["event_id"].startswith("node:") and event["event_id"].endswith(":terminal")
        }
        items.append(
            {
                "request_id": request["request_id"],
                "workflow_id": row["workflow_id"],
                "created_at": row["created_at"].isoformat(),
                "display_name": row["display_name"] or "Retained source build",
                "transformation": request["transformation"],
                "valid_at": request["valid_at"],
                "known_at": request["known_at"],
                "completed_steps": sum(
                    event.get("state") == "COMPLETED" for event in terminals.values()
                ),
                "failed_steps": sum(event.get("state") == "FAILED" for event in terminals.values()),
                "budget_refused_steps": len(
                    {
                        event.get("node")
                        for event in retained["events"]
                        if event.get("state") == "BUDGET_REFUSED"
                    }
                ),
                "total_steps": len(compiled["nodes"]),
                "published_output_sets": len(retained["publications"]),
                "current_use_authorized": False,
                "business_effect_authorized": False,
            }
        )
    return {
        "purpose": "HISTORICAL_BUILD_EVIDENCE",
        "items": items,
        "next_cursor": {
            "created_at": page[-1]["created_at"].isoformat(),
            "request_id": page[-1]["workflow_id"].removeprefix("transformation:"),
        }
        if len(rows) > limit
        else None,
    }

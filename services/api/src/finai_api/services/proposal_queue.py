"""Keyset discovery of immutable proposals with current retained decisions."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def page(
    principal: Principal,
    limit: int = 25,
    snapshot_at: datetime | None = None,
    before_created_at: datetime | None = None,
    before_proposal_id: UUID | None = None,
) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    if not 1 <= limit <= 100:
        raise WorkspaceError(422, "Proposal queue limit must be between 1 and 100")
    if (before_created_at is None) != (before_proposal_id is None):
        raise WorkspaceError(422, "Proposal cursor requires both creation time and proposal ID")
    snapshot_at = snapshot_at or datetime.now(UTC)
    for value in (snapshot_at, before_created_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise WorkspaceError(422, "Proposal queue timestamps must include a timezone")
    predicate = ""
    params: list[Any] = [principal.scope.tenant_id, snapshot_at]
    if before_created_at is not None:
        # The redundant upper bound is an index condition, avoiding revisiting newer
        # pages before applying the mixed-direction tie predicate.
        predicate = "AND created_at<=%s AND (created_at<%s OR (created_at=%s AND proposal_id>%s)) "
        params.extend([before_created_at, before_created_at, before_created_at, before_proposal_id])
    params.append(limit + 1)
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        # RLS underestimates cardinality; the retained recency index bounds policy work
        # to the requested page. Preferences expire with this transaction.
        cursor.execute(
            "SELECT set_config('enable_sort','off',true), "
            "set_config('statement_timeout','10000',true)"
        )
        try:
            rows = cursor.execute(
                "WITH page AS MATERIALIZED ("
                "SELECT tenant_id,proposal_id,title,rationale,submitted_by,"
                "created_at,access_entity FROM resource_proposals "
                "WHERE tenant_id=%s AND created_at<=%s "
                + predicate
                + "ORDER BY created_at DESC,proposal_id LIMIT %s) "
                "SELECT p.proposal_id,p.title,p.rationale,p.submitted_by,p.created_at,"
                "p.access_entity,coalesce(d.decision,'PENDING') AS decision "
                "FROM page p LEFT JOIN LATERAL (SELECT decision FROM resource_decisions "
                "WHERE tenant_id=p.tenant_id AND proposal_id=p.proposal_id LIMIT 1) d ON true "
                "ORDER BY p.created_at DESC,p.proposal_id",
                params,
            ).fetchall()
        except psycopg.errors.QueryCanceled as exc:
            raise WorkspaceError(
                409, "Proposal queue exceeded its execution budget; no partial queue returned"
            ) from exc
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "proposals": rows,
        "has_more": has_more,
        "next_cursor": (
            {"created_at": rows[-1]["created_at"], "proposal_id": rows[-1]["proposal_id"]}
            if has_more
            else None
        ),
        "snapshot_at": snapshot_at,
        "decision_mode": "CURRENT_RETAINED_DECISION",
        "limit": limit,
    }

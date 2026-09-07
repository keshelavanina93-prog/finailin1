"""Discover reviewed analysis Functions in the server-owned company access scope."""

from datetime import UTC, datetime
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.certification import _current
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError


def discover(principal: Principal, after_resource_id: UUID | None = None) -> dict:
    require_permission(principal, "ontology_read")
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT v.* FROM resource_versions v WHERE tenant_id=%s AND access_entity=%s "
            "AND object_type='FunctionDefinition' AND authority_state='APPROVED' "
            "AND version_id=g8_effective_version_id(tenant_id,resource_id,%s) "
            "AND (%s::uuid IS NULL OR resource_id>%s) ORDER BY resource_id LIMIT 51",
            (
                principal.scope.tenant_id,
                principal.scope.legal_entity_id,
                datetime.now(UTC),
                after_resource_id,
                after_resource_id,
            ),
        ).fetchall()
        page = rows[:50]
        items = []
        for row in page:
            reference = VersionReference(
                resource_id=row["resource_id"], version_id=row["version_id"]
            )
            try:
                _current(cursor, principal, reference)
                upstream_authority(cursor, principal.scope.tenant_id, reference.version_id)
            except WorkspaceError as exc:
                if exc.status not in (404, 409):
                    raise
                continue
            items.append(
                {
                    "reference": reference.model_dump(mode="json"),
                    "display_name": row["display_name"],
                    "attributes": row["attributes"],
                    "content_hash": row["content_hash"],
                }
            )
    return {
        "items": items,
        "next_cursor": str(page[-1]["resource_id"]) if len(rows) > 50 else None,
        "purpose": "EVIDENCE_ANALYSIS_ONLY",
    }

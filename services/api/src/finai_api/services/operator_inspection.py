"""Knowledge-bounded operator inspection of exact canonical versions."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

MAX_VERSIONS = 1000
MAX_DEPENDENTS = 100


def inspect(
    principal: Principal,
    resource_id: UUID,
    version_id: UUID | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    known_at = known_at or datetime.now(UTC)
    if known_at.tzinfo is None:
        raise WorkspaceError(422, "Inspection knowledge time must include a timezone")
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        # Same publication sequencing and RLS boundary as historical graph inspection.
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        selected = cursor.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.system_from<=%s "
            "AND (%s::uuid IS NULL OR v.version_id=%s) "
            "ORDER BY v.system_from DESC,v.version_id DESC LIMIT 1",
            (principal.scope.tenant_id, resource_id, known_at, version_id, version_id),
        ).fetchone()
        if selected is None:
            raise WorkspaceError(404, "Resource version unavailable at this knowledge time")
        versions = cursor.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.system_from<=%s "
            "ORDER BY v.system_from DESC,v.version_id DESC LIMIT %s",
            (principal.scope.tenant_id, resource_id, known_at, MAX_VERSIONS + 1),
        ).fetchall()
        dependents = cursor.execute(
            "SELECT d.relation,v.resource_id,v.version_id,v.display_name,v.object_type "
            "FROM resource_dependencies d JOIN resource_versions v "
            "ON v.tenant_id=d.tenant_id AND v.version_id=d.version_id "
            "WHERE d.tenant_id=%s AND d.target_resource_id=%s AND d.target_version_id=%s "
            "AND v.system_from<=%s "
            "ORDER BY v.system_from DESC,v.version_id DESC,d.relation LIMIT %s",
            (
                principal.scope.tenant_id,
                resource_id,
                selected["version_id"],
                known_at,
                MAX_DEPENDENTS + 1,
            ),
        ).fetchall()
    return {
        "resource": CanonicalResource.model_validate(selected).model_dump(mode="json"),
        "versions": [
            CanonicalResource.model_validate(row).model_dump(mode="json")
            for row in versions[:MAX_VERSIONS]
        ],
        "dependents": [dict(row) for row in dependents[:MAX_DEPENDENTS]],
        "versions_truncated": len(versions) > MAX_VERSIONS,
        "dependents_truncated": len(dependents) > MAX_DEPENDENTS,
        "known_at": known_at.isoformat(),
        "selection_mode": "EXACT_VERSION" if version_id else "LATEST_KNOWN",
        "purpose": "HISTORICAL_INSPECTION",
        "current_use_authorized": False,
    }

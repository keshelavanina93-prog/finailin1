"""Resolve saved-query semantic dependencies inside the publication transaction."""

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.services.workspace import WorkspaceError


class TemporalDependencyUnavailable(WorkspaceError):
    def __init__(self) -> None:
        super().__init__(422, "Saved query dependency unavailable at its requested time")


def query_dependency(
    conn: psycopg.Connection[Any],
    tenant: UUID,
    identity: str,
    payload: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    query = ObjectSetQuery.model_validate(payload)
    valid_at, known_at = query.valid_at or now, query.known_at or now
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v JOIN canonical_identities i "
            "USING(tenant_id,resource_id) WHERE v.tenant_id=%s AND v.resource_id=%s "
            "AND v.system_from<=%s AND v.valid_from<=%s "
            "AND (v.valid_to IS NULL OR v.valid_to>%s) "
            "ORDER BY v.system_from DESC,v.version_id LIMIT 1",
            (tenant, identity, known_at, valid_at, valid_at),
        ).fetchone()
    if row is None or row["authority_state"] != "APPROVED":
        raise TemporalDependencyUnavailable()
    return dict(row)

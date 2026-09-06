"""Bounded as-of discovery over canonical versions and exact ownership pins."""

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.errors import QueryCanceled
from psycopg.rows import dict_row

from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

MAX_OFFSET = 2_147_483_647
SEARCH_TIMEOUT_MS = 15_000
OWNERSHIP_FIELDS = frozenset(
    {"company_id", "legal_entity_id", "chart_id", "ledger_id", "book_id", "scope_id"}
)


def project(
    rows: list[dict[str, Any]],
    pins: list[dict[str, Any]],
    company_id: UUID,
    effective_at: datetime,
    q: str,
    object_type: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    # Rows are knowledge-time bounded by the database. Select versions before text filtering:
    # an old label must never resurrect a superseded version in an as-of result.
    latest: dict[str, dict[str, Any]] = {}
    by_version = {str(row["version_id"]): row for row in rows}
    for row in rows:
        if row["valid_from"] > effective_at or (
            row["valid_to"] is not None and row["valid_to"] <= effective_at
        ):
            continue
        key = str(row["resource_id"])
        prior = latest.get(key)
        if prior is None or (row["system_from"], str(row["version_id"])) > (
            prior["system_from"],
            str(prior["version_id"]),
        ):
            latest[key] = row
    company = latest.get(str(company_id))
    if company is None or company["object_type"] != "LegalEntity":
        raise WorkspaceError(404, "Company is unavailable at the selected historical context")
    owned = {
        str(row["version_id"])
        for row in rows
        if str(row["resource_id"]) == str(company_id) and row["object_type"] == "LegalEntity"
    }
    edges: list[tuple[str, str]] = []
    for pin in pins:
        field = pin["relation"].removeprefix("FIELD:")
        source = by_version.get(str(pin["version_id"]))
        target = by_version.get(str(pin["target_version_id"]))
        if (
            pin["relation"].startswith("FIELD:")
            and field in OWNERSHIP_FIELDS
            and source is not None
            and target is not None
            and str(target["resource_id"]) == str(pin["target_resource_id"])
            and str(source["attributes"].get(field)) == str(target["resource_id"])
        ):
            edges.append((str(source["version_id"]), str(target["version_id"])))
    # Reverse reachability is cycle safe and bounded by the retained row count.
    incoming: dict[str, list[str]] = {}
    for source_version, target_version in edges:
        incoming.setdefault(target_version, []).append(source_version)
    pending = list(owned)
    while pending:
        for source_version in incoming.get(pending.pop(), []):
            if source_version not in owned:
                owned.add(source_version)
                pending.append(source_version)
    needle = q.strip().lower()
    discovered_matches = [
        row
        for row in latest.values()
        if str(row["version_id"]) in owned
        and (not needle or needle in row["display_name"].lower())
    ]
    # Facets describe the complete bounded historical result, never just its visible page.
    # Apply the chosen type afterwards so other matching categories remain discoverable.
    type_counts = Counter(row["object_type"] for row in discovered_matches)
    matched = sorted(
        (row for row in discovered_matches if not object_type or row["object_type"] == object_type),
        key=lambda row: (row["display_name"].lower(), str(row["resource_id"])),
    )
    return {
        "resources": [
            CanonicalResource.model_validate(row).model_dump(mode="json")
            for row in matched[offset : offset + limit]
        ],
        "has_more": len(matched) > offset + limit,
        "matched_count": len(matched),
        "type_facets": [
            {"object_type": kind, "count": type_counts[kind]} for kind in sorted(type_counts)
        ],
        "offset": offset,
        "limit": limit,
    }


def search(
    principal: Principal,
    company_id: UUID,
    q: str = "",
    object_type: str | None = None,
    effective_at: datetime | None = None,
    known_at: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    known_at = known_at or datetime.now(UTC)
    effective_at = effective_at or known_at
    if effective_at.tzinfo is None or known_at.tzinfo is None:
        raise WorkspaceError(422, "Historical timestamps must include a timezone")
    if not 0 <= offset <= MAX_OFFSET or not 1 <= limit <= 100 or len(q) > 200:
        raise WorkspaceError(422, "Historical search exceeds the supported page or query bound")
    with (
        resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        # The retained company may contain millions of observations. Keep traversal and
        # aggregation in PostgreSQL; only the requested page crosses into application memory.
        # UNION (not UNION ALL) makes exact-version reachability cycle safe. The indexed
        # target identity AND version comparison preserves immutable ownership evidence.
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)", (str(SEARCH_TIMEOUT_MS),)
        )
        try:
            result = cursor.execute(
                """WITH RECURSIVE owned(resource_id,version_id) AS (
                    SELECT resource_id,version_id FROM resource_versions
                    WHERE tenant_id=%(tenant)s AND resource_id=%(company)s
                      AND object_type='LegalEntity' AND system_from<=%(known)s
                    UNION
                    SELECT v.resource_id,v.version_id
                    FROM owned o JOIN resource_dependencies d
                      ON d.tenant_id=%(tenant)s AND d.target_resource_id=o.resource_id
                      AND d.target_version_id=o.version_id
                    JOIN resource_versions v
                      ON v.tenant_id=d.tenant_id AND v.version_id=d.version_id
                    WHERE d.relation=ANY(%(fields)s) AND v.system_from<=%(known)s
                      AND v.attributes->>substring(d.relation from 7)=d.target_resource_id::text
                ), identities AS (
                    SELECT DISTINCT resource_id FROM owned
                ), selected AS MATERIALIZED (
                    SELECT latest.*,i.identity_key FROM identities ids
                    CROSS JOIN LATERAL (
                        SELECT v.* FROM resource_versions v
                        WHERE v.tenant_id=%(tenant)s AND v.resource_id=ids.resource_id
                          AND v.system_from<=%(known)s AND v.valid_from<=%(effective)s
                          AND (v.valid_to IS NULL OR v.valid_to>%(effective)s)
                        ORDER BY v.system_from DESC,v.version_id DESC LIMIT 1
                    ) latest JOIN canonical_identities i
                      ON i.tenant_id=latest.tenant_id AND i.resource_id=latest.resource_id
                ), matches AS MATERIALIZED (
                    SELECT s.* FROM selected s JOIN owned o
                      ON o.resource_id=s.resource_id AND o.version_id=s.version_id
                    WHERE strpos(lower(s.display_name),lower(%(query)s))>0
                ), filtered AS (
                    SELECT * FROM matches
                    WHERE %(kind)s::text IS NULL OR object_type=%(kind)s
                ), page AS (
                    SELECT * FROM filtered
                    ORDER BY lower(display_name),resource_id
                    OFFSET %(offset)s LIMIT %(limit)s
                ) SELECT
                    EXISTS(SELECT 1 FROM selected WHERE resource_id=%(company)s
                           AND object_type='LegalEntity') AS company_available,
                    (SELECT count(*) FROM filtered) AS matched_count,
                    COALESCE((SELECT jsonb_agg(to_jsonb(page)
                        ORDER BY lower(display_name),resource_id) FROM page),
                        '[]'::jsonb) AS resources,
                    COALESCE((SELECT jsonb_agg(to_jsonb(f) ORDER BY object_type) FROM (
                        SELECT object_type,count(*) AS count FROM matches GROUP BY object_type
                    ) f),'[]'::jsonb) AS type_facets""",
                {
                    "tenant": principal.scope.tenant_id,
                    "company": company_id,
                    "known": known_at,
                    "effective": effective_at,
                    "fields": ["FIELD:" + field for field in sorted(OWNERSHIP_FIELDS)],
                    "query": q.strip(),
                    "kind": object_type,
                    "offset": offset,
                    "limit": limit,
                },
            ).fetchone()
        except QueryCanceled as exc:
            raise WorkspaceError(
                409,
                "Historical discovery exceeded its execution budget; no partial results returned",
            ) from exc
        if not result or not result["company_available"]:
            raise WorkspaceError(404, "Company is unavailable at the selected historical context")
        page_result = {
            "resources": [
                CanonicalResource.model_validate(row).model_dump(mode="json")
                for row in result["resources"]
            ],
            "matched_count": result["matched_count"],
            "type_facets": result["type_facets"],
            "has_more": result["matched_count"] > offset + limit,
            "offset": offset,
            "limit": limit,
        }

    return {
        **page_result,
        "company_id": str(company_id),
        "effective_at": effective_at.isoformat(),
        "known_at": known_at.isoformat(),
        "purpose": "HISTORICAL_DISCOVERY",
        "current_use_authorized": False,
    }

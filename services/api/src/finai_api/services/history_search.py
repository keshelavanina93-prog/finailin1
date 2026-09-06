"""Bounded as-of discovery over canonical versions and exact ownership pins."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

MAX_VERSIONS = 5000
MAX_PINS = 20000
MAX_OWNERSHIP_DEPTH = 16
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
    needle = q.strip().casefold()
    matched = sorted(
        (
            row
            for row in latest.values()
            if str(row["version_id"]) in owned
            and (not object_type or row["object_type"] == object_type)
            and (not needle or needle in row["display_name"].casefold())
        ),
        key=lambda row: (row["display_name"].casefold(), str(row["resource_id"])),
    )
    return {
        "resources": [
            CanonicalResource.model_validate(row).model_dump(mode="json")
            for row in matched[offset : offset + limit]
        ],
        "has_more": len(matched) > offset + limit,
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
    if not 0 <= offset <= MAX_VERSIONS or not 1 <= limit <= 100 or len(q) > 200:
        raise WorkspaceError(422, "Historical search exceeds the supported page or query bound")
    with (
        resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        # Start with the selected company, then follow reverse exact ownership pins.
        # The bound applies to this company, never to unrelated tenant history.
        rows = cursor.execute(
            "SELECT v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.object_type='LegalEntity' "
            "AND v.system_from<=%s "
            "ORDER BY v.system_from,v.version_id LIMIT %s",
            (principal.scope.tenant_id, company_id, known_at, MAX_VERSIONS + 1),
        ).fetchall()
        discovered = {row["version_id"]: row for row in rows}
        frontier = list(discovered)
        for depth in range(MAX_OWNERSHIP_DEPTH + 1):
            if not frontier:
                break
            if len(discovered) > MAX_VERSIONS:
                raise WorkspaceError(409, "Company history exceeds the retained version bound")
            children = cursor.execute(
                "SELECT DISTINCT v.*,i.identity_key FROM resource_dependencies d "
                "JOIN resource_versions v ON v.tenant_id=d.tenant_id AND v.version_id=d.version_id "
                "JOIN canonical_identities i ON i.tenant_id=v.tenant_id "
                "AND i.resource_id=v.resource_id "
                "WHERE d.tenant_id=%s AND d.target_version_id=ANY(%s::uuid[]) "
                "AND d.relation=ANY(%s::text[]) AND v.system_from<=%s "
                "AND v.attributes->>substring(d.relation from 7)=d.target_resource_id::text "
                "AND NOT (v.version_id=ANY(%s::uuid[])) LIMIT %s",
                (
                    principal.scope.tenant_id,
                    frontier,
                    ["FIELD:" + field for field in sorted(OWNERSHIP_FIELDS)],
                    known_at,
                    list(discovered),
                    MAX_VERSIONS + 1 - len(discovered),
                ),
            ).fetchall()
            if children and depth == MAX_OWNERSHIP_DEPTH:
                raise WorkspaceError(409, "Company history exceeds the ownership depth bound")
            frontier = [row["version_id"] for row in children]
            discovered.update({row["version_id"]: row for row in children})
        # Include the selected as-of version even if a later correction moved an identity
        # to another company. project() must exclude it, not resurrect its old owner.
        selected = cursor.execute(
            "SELECT DISTINCT ON(v.resource_id) v.*,i.identity_key FROM resource_versions v "
            "JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.resource_id=ANY(%s::uuid[]) AND v.system_from<=%s "
            "AND v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
            "ORDER BY v.resource_id,v.system_from DESC,v.version_id DESC LIMIT %s",
            (
                principal.scope.tenant_id,
                list({r["resource_id"] for r in discovered.values()}),
                known_at,
                effective_at,
                effective_at,
                MAX_VERSIONS + 1,
            ),
        ).fetchall()
        discovered.update({row["version_id"]: row for row in selected})
        rows = list(discovered.values())
        if len(rows) > MAX_VERSIONS:
            raise WorkspaceError(409, "Historical search exceeds the retained version bound")
        pins = cursor.execute(
            "SELECT version_id,target_resource_id,target_version_id,relation "
            "FROM resource_dependencies WHERE tenant_id=%s "
            "AND version_id=ANY(%s::uuid[]) ORDER BY version_id,target_version_id,relation "
            "LIMIT %s",
            (principal.scope.tenant_id, [row["version_id"] for row in rows], MAX_PINS + 1),
        ).fetchall()
        if len(pins) > MAX_PINS:
            raise WorkspaceError(409, "Historical search exceeds the retained ownership bound")
    return {
        **project(rows, pins, company_id, effective_at, q, object_type, offset, limit),
        "company_id": str(company_id),
        "effective_at": effective_at.isoformat(),
        "known_at": known_at.isoformat(),
        "purpose": "HISTORICAL_DISCOVERY",
        "current_use_authorized": False,
    }

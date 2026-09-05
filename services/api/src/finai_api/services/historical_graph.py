"""Historical dependency lineage follows recorded version pins, never current heads."""

from collections import deque
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.review import Principal
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

MAX_DEPTH = 16
MAX_NODES = 1000
MAX_EDGES = 5000


def historical_graph(
    principal: Principal,
    resource_id: UUID,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    if any(value is not None and value.tzinfo is None for value in (valid_at, known_at)):
        raise WorkspaceError(422, "Historical timestamps must include a timezone")
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        # Match registry writer sequencing so one lineage read cannot mix an in-flight acceptance.
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        known_at = known_at or datetime.now(UTC)
        valid_at = valid_at or known_at
        root = cursor.execute(
            "SELECT resource_id,version_id,object_type,display_name,authority_state,"
            "valid_from,valid_to,system_from FROM resource_versions "
            "WHERE tenant_id=%s AND resource_id=%s AND system_from<=%s "
            "AND valid_from<=%s AND (valid_to IS NULL OR valid_to>%s) "
            "ORDER BY system_from DESC,version_id LIMIT 1",
            (principal.scope.tenant_id, resource_id, known_at, valid_at, valid_at),
        ).fetchone()
        if root is None:
            raise WorkspaceError(404, "Historical resource not found in authorized context")
        root_version = str(root["version_id"])
        nodes: dict[str, dict[str, Any]] = {root_version: root}
        pending = deque([(root_version, 0)])
        edges: set[tuple[str, str, str]] = set()
        while pending:
            source_version, depth = pending.popleft()
            dependencies = cursor.execute(
                "SELECT target_resource_id,target_version_id,relation FROM resource_dependencies "
                "WHERE tenant_id=%s AND version_id=%s "
                "ORDER BY target_version_id,relation LIMIT %s",
                (principal.scope.tenant_id, UUID(source_version), MAX_EDGES + 1),
            ).fetchall()
            if len(dependencies) > MAX_EDGES:
                raise WorkspaceError(409, "Historical lineage exceeds the edge bound")
            for dependency in dependencies:
                target_version = str(dependency["target_version_id"])
                edges.add((source_version, target_version, dependency["relation"]))
                if len(edges) > MAX_EDGES:
                    raise WorkspaceError(409, "Historical lineage exceeds the edge bound")
                if target_version in nodes:
                    if str(nodes[target_version]["resource_id"]) != str(
                        dependency["target_resource_id"]
                    ):
                        raise WorkspaceError(
                            409, "Historical lineage contains an inconsistent version pin"
                        )
                    continue
                if depth >= MAX_DEPTH or len(nodes) >= MAX_NODES:
                    raise WorkspaceError(409, "Historical lineage exceeds the depth or node bound")
                target_node = cursor.execute(
                    "SELECT resource_id,version_id,object_type,display_name,authority_state,"
                    "valid_from,valid_to,system_from FROM resource_versions "
                    "WHERE tenant_id=%s AND resource_id=%s AND version_id=%s",
                    (
                        principal.scope.tenant_id,
                        dependency["target_resource_id"],
                        dependency["target_version_id"],
                    ),
                ).fetchone()
                if target_node is None:
                    raise WorkspaceError(
                        404, "Historical lineage is incomplete in authorized context"
                    )
                if target_node["system_from"] > known_at:
                    raise WorkspaceError(
                        409,
                        "Historical lineage includes a dependency not yet recorded "
                        "at the requested knowledge time",
                    )
                nodes[target_version] = target_node
                pending.append((target_version, depth + 1))
        # Detect cycles between versions; diamonds and multiple versions of one identity are valid.
        neighbors: dict[str, set[str]] = {key: set() for key in nodes}
        for source, target, _ in edges:
            neighbors[source].add(target)
        indegree = {key: 0 for key in nodes}
        for targets in neighbors.values():
            for target in targets:
                indegree[target] += 1
        ready = deque(key for key, value in indegree.items() if value == 0)
        longest = {key: 0 for key in nodes}
        visited = 0
        while ready:
            source = ready.popleft()
            visited += 1
            for target in neighbors[source]:
                longest[target] = max(longest[target], longest[source] + 1)
                if longest[target] > MAX_DEPTH:
                    raise WorkspaceError(409, "Historical lineage exceeds the depth bound")
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        if visited != len(nodes):
            raise WorkspaceError(409, "Historical lineage contains a dependency cycle")
        return {
            "purpose": "HISTORICAL_LINEAGE",
            "root_resource_id": str(resource_id),
            "root_version_id": root_version,
            "valid_at": valid_at,
            "known_at": known_at,
            "max_depth": MAX_DEPTH,
            "max_nodes": MAX_NODES,
            "max_edges": MAX_EDGES,
            "nodes": [
                {
                    **node,
                    "resource_id": str(node["resource_id"]),
                    "version_id": str(node["version_id"]),
                }
                for _, node in sorted(nodes.items())
            ],
            "edges": [
                {"source_version_id": source, "target_version_id": target, "relation": relation}
                for source, target, relation in sorted(edges)
            ],
        }

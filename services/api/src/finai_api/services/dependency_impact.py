"""Retained, bounded reverse dependency snapshots with hidden-consumer refusal."""

import json
from collections import deque
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from finai_api.domain.resources import ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services.workspace import WorkspaceError

MAX_DEPTH = 16
MAX_RESOURCES = 1000


def impact_fingerprint(snapshot: dict[str, Any]) -> str:
    return sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def downstream_impact(
    conn: psycopg.Connection[Any],
    principal: Principal,
    proposal: ResourceProposal,
    dependencies: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    mutations = {str(item.resource_id): item for item in proposal.mutations}
    proposed_versions = {str(uuid5(proposal.proposal_id, key)) for key in mutations}
    proposed_reverse: dict[str, list[dict[str, Any]]] = {}
    for identifier, refs in dependencies.items():
        mutation = mutations[identifier]
        for target in {ref["resource_id"] for ref in refs}:
            proposed_reverse.setdefault(target, []).append(
                {
                    "resource_id": identifier,
                    "version_id": str(uuid5(proposal.proposal_id, identifier)),
                    "object_type": mutation.object_type,
                    "display_name": mutation.display_name,
                    "state": "PROPOSED",
                    "cycle_dependency": any(
                        not ref["relation"].startswith("BOUND_SOURCE:")
                        or ref["version_id"] in proposed_versions
                        for ref in refs
                        if ref["resource_id"] == target
                    ),
                }
            )
    return _traverse(
        conn,
        principal,
        {
            identifier: item.expected_version_id is not None
            for identifier, item in mutations.items()
        },
        proposed_reverse,
        proposal.access_entity,
    )


def current_impact(
    conn: psycopg.Connection[Any], principal: Principal, root_versions: dict[str, str]
) -> dict[str, Any]:
    """Trace accepted dependencies without constructing or publishing a change proposal."""
    if not root_versions or len(root_versions) > MAX_RESOURCES:
        raise WorkspaceError(422, "Select a bounded set of accepted root versions")
    for identity, version in root_versions.items():
        row = conn.execute(
            "SELECT 1 FROM resource_heads h JOIN resource_versions v "
            "USING(tenant_id,resource_id,version_id) WHERE h.tenant_id=%s "
            "AND h.resource_id=%s AND h.version_id=%s AND v.authority_state='APPROVED'",
            (principal.scope.tenant_id, UUID(identity), UUID(version)),
        ).fetchone()
        if not row:
            raise WorkspaceError(409, "Impact root is not an accepted current version")
    result = _traverse(conn, principal, dict.fromkeys(root_versions, True), {}, "__TENANT__")
    result["selection"] = "CURRENT_ACCEPTED_HEADS"
    result["roots"] = [
        {"resource_id": key, "version_id": value} for key, value in sorted(root_versions.items())
    ]
    return result


def _traverse(
    conn: psycopg.Connection[Any],
    principal: Principal,
    expected_roots: dict[str, bool],
    proposed_reverse: dict[str, list[dict[str, Any]]],
    access_entity: str,
) -> dict[str, Any]:
    neighbors: dict[str, list[dict[str, Any]]] = {}
    unique_resources: set[str] = set(expected_roots)
    restricted = False

    def children(identifier: str) -> list[dict[str, Any]]:
        nonlocal restricted
        if identifier in neighbors:
            return neighbors[identifier]
        visible = conn.execute(
            "SELECT 1 FROM resource_heads WHERE tenant_id=%s AND resource_id=%s",
            (principal.scope.tenant_id, UUID(identifier)),
        ).fetchone()
        if visible:
            hidden = conn.execute(
                "SELECT public.g8_has_hidden_current_dependents(%s)", (UUID(identifier),)
            ).fetchone()
            if hidden and hidden[0]:
                raise WorkspaceError(
                    409,
                    "Complete dependency impact requires an authorized "
                    "tenant steward; proposal cannot be accepted",
                )
        elif identifier not in expected_roots or expected_roots[identifier]:
            raise WorkspaceError(409, "Complete dependency impact is unavailable in this context")
        # A new identity has no accepted version for any current resource to reference.
        # Traverse its proposed dependents below without scanning persisted dependencies.
        rows = []
        if visible:
            with conn.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    "SELECT v.resource_id,v.version_id,v.object_type,"
                    "v.display_name,v.access_entity,"
                    "bool_or(left(d.relation,13)<>'BOUND_SOURCE:') AS cycle_dependency "
                    "FROM resource_dependencies d JOIN resource_heads h "
                    "ON h.tenant_id=d.tenant_id AND h.version_id=d.version_id "
                    "JOIN resource_versions v ON v.tenant_id=h.tenant_id "
                    "AND v.version_id=h.version_id "
                    "WHERE d.tenant_id=%s AND d.target_resource_id=%s "
                    "AND v.authority_state='APPROVED' "
                    "GROUP BY v.resource_id,v.version_id,v.object_type,"
                    "v.display_name,v.access_entity "
                    "ORDER BY v.resource_id,v.version_id LIMIT %s",
                    (principal.scope.tenant_id, UUID(identifier), MAX_RESOURCES + 1),
                ).fetchall()
        if len(rows) > MAX_RESOURCES:
            raise WorkspaceError(
                409, "Dependency impact exceeds the resource bound; narrow the change"
            )
        if access_entity != "__TENANT__" and any(
            row["access_entity"] not in (access_entity, "__PLATFORM__") for row in rows
        ):
            restricted = True
        for row in rows:
            row.pop("access_entity")
        result = [
            {
                **row,
                "resource_id": str(row["resource_id"]),
                "version_id": str(row["version_id"]),
                "state": "CURRENT",
            }
            for row in rows
        ]
        result.extend(proposed_reverse.get(identifier, []))
        unique_resources.update(row["resource_id"] for row in result)
        if len(unique_resources) > MAX_RESOURCES:
            raise WorkspaceError(
                409, "Dependency impact exceeds the resource bound; narrow the change"
            )
        neighbors[identifier] = result
        return result

    affected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for root in sorted(expected_roots):
        pending = deque([(root, 0)])
        seen = {root}
        while pending:
            identifier, depth = pending.popleft()
            for child in children(identifier):
                child_id = child["resource_id"]
                key = (root, child_id, child["version_id"])
                if key not in affected:
                    affected[key] = {
                        "root_resource_id": root,
                        **{key: value for key, value in child.items() if key != "cycle_dependency"},
                        "depth": depth + 1,
                    }
                if len(affected) > MAX_RESOURCES:
                    raise WorkspaceError(
                        409, "Dependency impact exceeds the snapshot bound; narrow the change"
                    )
                if child_id not in seen:
                    if depth >= MAX_DEPTH:
                        raise WorkspaceError(
                            409, "Dependency impact exceeds the depth bound; narrow the change"
                        )
                    seen.add(child_id)
                    pending.append((child_id, depth + 1))
    # Retained source versions are immutable provenance, not live feedback edges.
    # Keep them in impact/security traversal; only live or co-proposed dependencies
    # participate in the topology cycle check. A FIELD edge is never exempted.
    edges = {
        node: {child["resource_id"] for child in values if child.get("cycle_dependency", True)}
        for node, values in neighbors.items()
    }
    indegree = {node: 0 for node in unique_resources}
    for targets in edges.values():
        for target in targets:
            indegree[target] += 1
    ready = deque(node for node, count in indegree.items() if count == 0)
    removed = 0
    while ready:
        node = ready.popleft()
        removed += 1
        for target in edges.get(node, set()):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if removed != len(indegree):
        raise WorkspaceError(409, "Dependency impact contains a cycle; resolve it before promotion")
    return {
        "status": "COMPLETE",
        "requires_tenant_steward": restricted,
        "selection": "CURRENT_ACCEPTED_HEADS_AND_PROPOSED",
        "max_depth": MAX_DEPTH,
        "max_resources": MAX_RESOURCES,
        "affected": [affected[key] for key in sorted(affected)],
    }

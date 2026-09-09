"""Live graph projection over accepted, version-pinned ontology dependencies."""

import json
from typing import Any

from psycopg.types.json import Jsonb

from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.services.resources import resource_connection
from finai_api.storage import connection


def source_connections(principal: Principal) -> list[dict[str, Any]]:
    """Project already-bound source references; never infer company/account joins by name."""
    if not {"read", "export"}.issubset(principal.permissions):
        return []
    scope = principal.scope.model_dump(mode="json")
    result: list[dict[str, Any]] = []
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        rows = conn.execute(
            "SELECT receipt_id,receipt FROM hydration_runs WHERE tenant_id=%s "
            "AND exact_scope=%s ORDER BY ingested_at DESC,receipt_id LIMIT 50",
            (principal.scope.tenant_id, Jsonb(scope)),
        ).fetchall()
        for receipt_id, receipt in rows:
            refs = dict(receipt.get("canonical_references", {}))
            for item in receipt.get("candidates", []):
                for field, ref in item.get("canonical_references", {}).items():
                    refs[f"{field}:{ref['resource_id']}"] = ref
            for field, ref in refs.items():
                result.append(
                    {
                        "receipt_id": receipt_id,
                        "source_sha256": receipt["source_sha256"],
                        "target": ref["resource_id"],
                        "target_version": ref["version_id"],
                        "label": field.split(":")[0],
                        "binding_state": receipt["binding_state"],
                    }
                )
    return result


def connections(principal: Principal, nodes: list[CanonicalResource]) -> list[dict[str, Any]]:
    if not nodes:
        return []
    visible = {str(node.resource_id): node for node in nodes}
    versions = [node.version_id for node in nodes]
    edges: list[dict[str, Any]] = []
    pins = {}
    with resource_connection(principal) as conn:
        rows = conn.execute(
            "SELECT v.resource_id,d.version_id,d.target_resource_id,d.target_version_id,"
            "d.relation FROM resource_dependencies d JOIN resource_versions v "
            "ON v.tenant_id=d.tenant_id AND v.version_id=d.version_id "
            "WHERE d.tenant_id=%s AND d.version_id=ANY(%s) "
            "AND d.relation LIKE 'FIELD:%%' ORDER BY v.resource_id,d.relation",
            (principal.scope.tenant_id, versions),
        ).fetchall()
        for source, version, target, target_version, relation in rows:
            pins[(str(version), relation)] = str(target_version)
            a, b = visible.get(str(source)), visible.get(str(target))
            if a is None or b is None or a.object_type == "Relationship":
                continue
            if b.object_type in {"SchemaDefinition", "SemanticContract", "LinkType"}:
                continue
            edges.append(
                {
                    "id": f"{version}:{relation}:{target_version}",
                    "source": str(source),
                    "target": str(target),
                    "label": relation.removeprefix("FIELD:"),
                    "source_version": str(version),
                    "target_version": str(target_version),
                    "state": "CURRENT"
                    if b.version_id == target_version
                    else "PINNED_PRIOR_VERSION",
                }
            )
    for node in nodes:
        if node.object_type != "Relationship":
            continue
        source, target = (
            str(node.attributes.get("source_id")),
            str(node.attributes.get("target_id")),
        )
        if source in visible and target in visible:
            source_pin = pins.get((str(node.version_id), "FIELD:source_id"))
            target_pin = pins.get((str(node.version_id), "FIELD:target_id"))
            state = (
                "CURRENT"
                if (
                    source_pin == str(visible[source].version_id)
                    and target_pin == str(visible[target].version_id)
                )
                else "PINNED_PRIOR_VERSION"
            )
            if source_pin is None or target_pin is None:
                state = "DEPENDENCY_UNAVAILABLE"
            edges.append(
                {
                    "id": str(node.version_id),
                    "source": source,
                    "target": target,
                    "label": node.display_name,
                    "source_version": source_pin,
                    "target_version": target_pin,
                    "relationship_version": str(node.version_id),
                    "state": state,
                }
            )
    return edges

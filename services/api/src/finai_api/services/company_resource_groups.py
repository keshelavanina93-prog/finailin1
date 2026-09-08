"""Canonical type-group/interface projections over explicit company connections only."""

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from pydantic import ValidationError

from finai_api.domain.company_condition import CompanyOperatingResourceGroup
from finai_api.domain.resources import CanonicalResource
from finai_api.services import interface_query, resources, type_group_query
from finai_api.services.workspace import WorkspaceError

DEFINITION_TYPES = ["ObjectTypeGroup", "ObjectInterface", "ObjectTypeImplementation", "DomainPack"]
LIMIT = 500


def definitions(principal, valid: datetime, known: datetime):
    """One bounded RLS snapshot; exact dependencies never advance the knowledge cutoff."""
    with (
        resources.resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        cur.execute("SELECT set_config('statement_timeout','10000',true)")
        rows = cur.execute(
            "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) v.*,i.identity_key "
            "FROM resource_versions v JOIN canonical_identities i USING(tenant_id,resource_id) "
            "WHERE v.tenant_id=%s AND v.object_type=ANY(%s) AND v.system_from<=%s "
            "AND v.valid_from<=%s AND (v.valid_to IS NULL OR v.valid_to>%s) "
            "ORDER BY v.resource_id,v.system_from DESC,v.version_id) s "
            "WHERE authority_state='APPROVED' AND evidence_class<>'REFERENCE_TEMPLATE' "
            "ORDER BY resource_id LIMIT %s",
            (principal.scope.tenant_id, DEFINITION_TYPES, known, valid, valid, LIMIT + 1),
        ).fetchall()
        if len(rows) > LIMIT:
            raise WorkspaceError(409, "Company group definition snapshot exceeds its bound")
        cache: dict[tuple[str, str], Any] = {}

        def load(identity, version):
            key = (str(identity), str(version))
            if key in cache:
                return cache[key]
            row = cur.execute(
                "SELECT v.*,i.identity_key FROM resource_versions v JOIN canonical_identities i "
                "USING(tenant_id,resource_id) WHERE v.tenant_id=%s AND v.resource_id=%s "
                "AND v.version_id=%s AND v.system_from<=%s AND v.valid_from<=%s "
                "AND (v.valid_to IS NULL OR v.valid_to>%s)",
                (principal.scope.tenant_id, identity, version, known, valid, valid),
            ).fetchone()
            if not row or row["authority_state"] != "APPROVED":
                raise WorkspaceError(409, "Exact group dependency is unavailable at this snapshot")
            if (
                row["object_type"] != "SchemaDefinition"
                and row["evidence_class"] == "REFERENCE_TEMPLATE"
            ):
                raise WorkspaceError(409, "Reference template cannot define operating membership")
            deps = cur.execute(
                "SELECT d.relation,v.resource_id,v.version_id,v.content_hash "
                "FROM resource_dependencies d JOIN resource_versions v "
                "ON v.tenant_id=d.tenant_id AND v.version_id=d.target_version_id "
                "WHERE d.tenant_id=%s AND d.version_id=%s LIMIT 501",
                (principal.scope.tenant_id, version),
            ).fetchall()
            if len(deps) > LIMIT:
                raise WorkspaceError(409, "Group dependency count exceeds its bound")
            row["dependencies"] = deps
            cache[key] = row
            return row

        return resolve_definitions(rows, load)


def resolve_definitions(rows, load):
    """Reuse the platform's type/interface validation, including schema and implementation pins."""
    resolved = []
    for row in rows:
        if row["object_type"] == "ObjectTypeImplementation":
            continue
        node = CanonicalResource.model_validate(row)
        selection = {"resource_id": node.resource_id, "version_id": node.version_id}
        pins = [{**selection, "content_hash": node.content_hash}]
        schemas = {}
        reason = None
        try:
            if node.object_type == "ObjectTypeGroup":
                binding = type_group_query.resolve_with_loader(selection, load)
                for item in binding["schemas"]:
                    schemas[item["object_type"]] = item["schema"]["version_id"]
                    pins.append(item["schema"])
            elif node.object_type == "ObjectInterface":
                implementations = []
                for item in rows:
                    if item["object_type"] == "ObjectTypeImplementation" and item["attributes"].get(
                        "interface_id"
                    ) == str(node.resource_id):
                        exact = load(item["resource_id"], item["version_id"])
                        if any(
                            p["relation"] == "FIELD:interface_id"
                            and str(p["version_id"]) == str(node.version_id)
                            for p in exact["dependencies"]
                        ):
                            implementations.append(
                                {k: item[k] for k in ("resource_id", "version_id")}
                            )
                if not implementations:
                    raise WorkspaceError(409, "No accepted implementation pins at this snapshot")
                binding = interface_query.resolve_with_loader(
                    {**selection, "implementations": implementations},
                    load,
                )
                for item in binding["implementations"]:
                    schemas[item["object_type"]] = item["schema"]["version_id"]
                    pins.extend([item["implementation"], item["schema"]])
            else:
                schemas, dependencies = pack_membership(node, rows, load)
                pins.extend(dependencies)
        except (WorkspaceError, ValidationError) as exc:
            reason = str(exc)
        resolved.append((node, schemas, pins, reason))
    return resolved


def project(resolved, connections, valid, known):
    targets = {edge.target.resource_id: edge.target for edge in connections}
    result = []
    for node, schemas, pins, reason in resolved:
        candidates = [n for n in targets.values() if n.object_type in schemas]
        if any(str(n.schema_version_id) != str(schemas[n.object_type]) for n in candidates):
            reason = "Connected member schema differs from the exact group definition pin."
        members = (
            [] if reason else sorted(candidates, key=lambda n: (n.display_name, str(n.resource_id)))
        )
        result.append(
            CompanyOperatingResourceGroup(
                key=str(node.resource_id),
                label=node.display_name,
                definition=node,
                definition_pins=pins,
                state="UNAVAILABLE" if reason else "AVAILABLE" if members else "EMPTY",
                resources=members,
                valid_at=valid,
                known_at=known,
                count=None if reason else len(members),
                completeness="UNAVAILABLE" if reason else "COMPLETE_WITHIN_CONNECTION_SNAPSHOT",
                reason=reason
                or "Exact accepted outgoing company connections only; not ownership, live "
                "condition, financial authority or a complete company inventory. "
                "Groups may overlap.",
            )
        )
    return result


def pack_membership(node, rows, load):
    """A pack delegates membership to one reviewed definition, never a local type list."""
    fields = {
        "membership_group_id": "ObjectTypeGroup",
        "membership_interface_id": "ObjectInterface",
    }
    selected = [field for field in fields if node.attributes.get(field) is not None]
    if len(selected) != 1:
        raise WorkspaceError(
            409, "DomainPack requires exactly one accepted membership definition reference"
        )
    field = selected[0]
    pack = load(node.resource_id, node.version_id)
    if (
        not pack
        or str(pack["resource_id"]) != str(node.resource_id)
        or str(pack["version_id"]) != str(node.version_id)
        or pack["content_hash"] != node.content_hash
        or pack["authority_state"] != "APPROVED"
    ):
        raise WorkspaceError(409, "DomainPack exact definition is unavailable")
    refs = [p for p in pack.get("dependencies", []) if p["relation"] == "FIELD:" + field]
    if len(refs) != 1 or str(refs[0]["resource_id"]) != str(node.attributes[field]):
        raise WorkspaceError(409, "DomainPack membership requires one exact matching FIELD pin")
    ref = refs[0]
    target = load(ref["resource_id"], ref["version_id"])
    if (
        not target
        or str(target["resource_id"]) != str(ref["resource_id"])
        or str(target["version_id"]) != str(ref["version_id"])
        or target["content_hash"] != ref["content_hash"]
        or target["authority_state"] != "APPROVED"
        or target["evidence_class"] == "REFERENCE_TEMPLATE"
        or target["object_type"] != fields[field]
    ):
        raise WorkspaceError(
            409, "DomainPack membership target differs from accepted exact definition"
        )
    # Reuse the same shared group/interface resolver; nested packs cannot recurse.
    candidates = [
        target,
        *[row for row in rows if row["object_type"] == "ObjectTypeImplementation"],
    ]
    _, schemas, pins, reason = resolve_definitions(candidates, load)[0]
    if reason:
        raise WorkspaceError(409, "DomainPack membership unavailable: " + reason)
    identities = [str(pin["resource_id"]) for pin in pins]
    if len(pins) + 1 > 201 or len(set(identities)) != len(identities):
        raise WorkspaceError(409, "DomainPack membership exceeds unique exact definition pin bound")
    return schemas, pins

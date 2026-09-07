"""Exact reviewed type groups over original canonical objects, without substitution."""

from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.object_sets import InterfacePin
from finai_api.domain.ontology_definitions import TypeGroupDefinition
from finai_api.services.workspace import WorkspaceError


def _pin(row):
    return {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}


def resolve_with_loader(selection, load):
    selection = InterfacePin.model_validate(selection)

    def exact(identity, version, kind):
        row = load(UUID(str(identity)), UUID(str(version)))
        if (
            not row
            or str(row["resource_id"]) != str(identity)
            or str(row["version_id"]) != str(version)
            or row["object_type"] != kind
            or row["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(409, "Exact reviewed type group dependency is unavailable")
        return row

    group = exact(selection.resource_id, selection.version_id, "ObjectTypeGroup")
    definition = TypeGroupDefinition.model_validate(group["attributes"]["definition"])
    if len(set(definition.types)) != len(definition.types):
        raise WorkspaceError(422, "Type group concrete types must be unique")
    schemas = []
    common = None
    for name in definition.types:
        refs = [
            dep
            for dep in group.get("dependencies", [])
            if dep["relation"] == "DEFINITION_TYPE:" + name
        ]
        if len(refs) != 1:
            raise WorkspaceError(409, "Type group requires one exact schema pin per declared type")
        schema = exact(refs[0]["resource_id"], refs[0]["version_id"], "SchemaDefinition")
        if schema["identity_key"] != name:
            raise WorkspaceError(409, "Type group schema pin belongs to another concrete type")
        fields = {
            field: {key: value for key, value in spec.items() if key != "field_id"}
            for field, spec in schema["attributes"]["fields"].items()
        }
        common = (
            fields
            if common is None
            else {field: spec for field, spec in common.items() if fields.get(field) == spec}
        )
        schemas.append({"object_type": name, "schema": _pin(schema)})
    return {"group": _pin(group), "schemas": schemas, "fields": common or {}}


def resolve(principal, selection, valid_at=None, known_at=None):
    # Static exact definition pins do not advance the query's data cutoff.
    from finai_api.services.ontology_definitions import definition
    from finai_api.services.resources import resource_connection

    def load(identity, version):
        try:
            return definition(principal, identity, version)
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
                row = cur.execute(
                    "SELECT v.*,i.identity_key FROM resource_versions v "
                    "JOIN canonical_identities i USING(tenant_id,resource_id) "
                    "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.version_id=%s "
                    "AND v.object_type='SchemaDefinition'",
                    (principal.scope.tenant_id, identity, version),
                ).fetchone()
            if row is None:
                raise WorkspaceError(409, "Exact type group schema is unavailable") from exc
            return row

    return resolve_with_loader(selection, load)


def compiler_binding(binding):
    """Private identity mappings for the existing global SQL compiler."""
    return {
        "fields": binding["fields"],
        "implementations": [
            {**item, "fields": {name: name for name in binding["fields"]}}
            for item in binding["schemas"]
        ],
    }


def values(binding, objects):
    schemas = {item["object_type"]: item["schema"] for item in binding["schemas"]}
    return [
        {
            "object_id": obj["resource_id"],
            "object_version_id": obj["version_id"],
            "schema_version_id": schemas[obj["object_type"]]["version_id"],
            "status": "AVAILABLE"
            if str(obj["schema_version_id"]) == schemas[obj["object_type"]]["version_id"]
            else "SCHEMA_CHANGED",
        }
        for obj in objects
    ]

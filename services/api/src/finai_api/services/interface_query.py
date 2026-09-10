"""Exact reviewed interface substitution shared by publication and query execution."""

from types import SimpleNamespace
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.object_sets import InterfaceRoot
from finai_api.domain.ontology_definitions import ImplementationDefinition, InterfaceDefinition
from finai_api.domain.resource_metadata import interface_value
from finai_api.services.workspace import WorkspaceError


def _pin(row):
    return {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}


def resolve_with_loader(selection, load):
    from finai_api.services.ontology_definition_validation import validate_definition

    selection = InterfaceRoot.model_validate(selection)
    original_load = load

    def exact_load(identity, version):
        row = original_load(identity, version)
        if (
            not row
            or str(row["resource_id"]) != str(identity)
            or str(row["version_id"]) != str(version)
        ):
            raise WorkspaceError(
                409, "Interface query requires the exact requested definition version"
            )
        return row

    load = exact_load
    interface = load(selection.resource_id, selection.version_id)
    if (
        not interface
        or interface["object_type"] != "ObjectInterface"
        or interface["authority_state"] != "APPROVED"
    ):
        raise WorkspaceError(409, "Exact reviewed interface is unavailable")
    definition = InterfaceDefinition.model_validate(interface["attributes"]["definition"])
    implementations = []
    seen = set()
    for ref in selection.implementations:
        item = load(ref.resource_id, ref.version_id)
        if (
            not item
            or item["object_type"] != "ObjectTypeImplementation"
            or item["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(409, "Exact reviewed interface implementation is unavailable")

        def dependency(field, item=item):
            pins = [r for r in item.get("dependencies", []) if r["relation"] == "FIELD:" + field]
            if len(pins) != 1 or str(pins[0]["resource_id"]) != item["attributes"].get(field):
                raise WorkspaceError(
                    409, "Exact interface implementation dependency is unavailable"
                )
            return pins[0]

        contract = dependency("interface_id")
        schema_ref = dependency("schema_id")
        if str(contract["resource_id"]) != str(selection.resource_id) or str(
            contract["version_id"]
        ) != str(selection.version_id):
            raise WorkspaceError(422, "Implementation belongs to another exact interface version")
        schema = load(UUID(str(schema_ref["resource_id"])), UUID(str(schema_ref["version_id"])))
        if (
            not schema
            or schema["object_type"] != "SchemaDefinition"
            or schema["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(409, "Exact implementation schema is unavailable")
        kind = schema["identity_key"]
        if kind in seen:
            raise WorkspaceError(
                422, "Interface query cannot select ambiguous implementations of one object type"
            )
        seen.add(kind)
        mapped = ImplementationDefinition.model_validate(item["attributes"]["definition"])
        validate_definition(
            SimpleNamespace(
                object_type="ObjectTypeImplementation",
                resource_id=item["resource_id"],
                attributes=item["attributes"],
            ),
            {},
            {},
            lambda identity, *_, schema=schema: (
                interface if identity == str(selection.resource_id) else schema
            ),
        )
        implementations.append(
            {
                "implementation": _pin(item),
                "schema": _pin(schema),
                "object_type": kind,
                "fields": mapped.fields,
            }
        )
    return {
        "interface": _pin(interface),
        "fields": definition.model_dump(mode="json")["fields"],
        "implementations": implementations,
    }


def resolve(principal, selection, valid_at=None, known_at=None):
    # Explicit static definition pins may postdate the data cutoff, as with saved sets.
    from finai_api.services.ontology_definitions import definition
    from finai_api.services.resources import resource_connection

    cache = {}

    def load(identity, version):
        key = (str(identity), str(version))
        if key not in cache:
            try:
                row = definition(principal, identity, version)
            except WorkspaceError as exc:
                if exc.status != 404:
                    raise
                with (
                    resource_connection(principal) as conn,
                    conn.cursor(row_factory=dict_row) as cursor,
                ):
                    row = cursor.execute(
                        "SELECT v.*,i.identity_key FROM resource_versions v "
                        "JOIN canonical_identities i USING(tenant_id,resource_id) "
                        "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.version_id=%s "
                        "AND v.object_type='SchemaDefinition'",
                        (principal.scope.tenant_id, identity, version),
                    ).fetchone()
                if row is None:
                    raise WorkspaceError(409, "Exact interface schema is unavailable") from exc
            cache[key] = row
        return cache[key]

    return resolve_with_loader(selection, load)


def values(binding, objects):
    mapped = {item["object_type"]: item for item in binding["implementations"]}
    result = []
    for obj in objects:
        implementation = mapped[obj["object_type"]]
        compatible = str(obj["schema_version_id"]) == implementation["schema"]["version_id"]
        result.append(
            {
                "object_id": obj["resource_id"],
                "object_version_id": obj["version_id"],
                "implementation_resource_id": implementation["implementation"]["resource_id"],
                "implementation_version_id": implementation["implementation"]["version_id"],
                "schema_version_id": implementation["schema"]["version_id"],
                "status": "AVAILABLE" if compatible else "SCHEMA_CHANGED",
                "values": {
                    name: interface_value(obj, field)
                    for name, field in implementation["fields"].items()
                }
                if compatible
                else None,
            }
        )
    return result

"""Bounded complete inputs assembled by the existing canonical Object Set compiler."""

from uuid import UUID

from psycopg.errors import QueryCanceled
from psycopg.types.json import Jsonb

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.services import ontology_definitions
from finai_api.services.object_sets import _query_objects
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

METADATA = (
    "counts_by_type",
    "filter_schema_versions",
    "traversal_schema_versions",
    "interface_bindings",
    "type_group_bindings",
    "interface_values",
    "type_group_values",
)
VALUES = ("interface_values", "type_group_values")


def page_hash(page, conn):
    return conn.execute(
        "SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex')",
        (Jsonb({k: v for k, v in page.items() if k != "page_hash"}),),
    ).fetchone()[0]


def pin(obj):
    return {k: str(obj[k]) for k in ("resource_id", "version_id", "content_hash")}


def validate(result, config, selected, conn):
    material = result.get("materialization")
    if (
        not isinstance(material, dict)
        or material.get("contract") != "bounded-object-set-materialization/1"
        or material.get("coverage") != "COMPLETE_BOUNDED_MATERIALIZATION"
        or material.get("hash_algorithm") != "POSTGRES_JSONB_TEXT_UTF8_SHA256"
    ):
        raise WorkspaceError(409, "Complete retained materialization is required")
    pages = material.get("pages", [])
    if (
        material.get("object_set") != selected
        or any(material.get(k) != config[k] for k in ("max_objects", "max_pages"))
        or not 1 <= len(pages) <= config["max_pages"]
        or material.get("page_count") != len(pages)
    ):
        raise WorkspaceError(409, "Materialization differs from its reviewed bounds or Object Set")
    objects = result["objects"]
    if (
        len(objects) > config["max_objects"]
        or result["total"] != len(objects)
        or material.get("object_count") != len(objects)
        or result["next_offset"] is not None
        or len({o["resource_id"] for o in objects}) != len(objects)
    ):
        raise WorkspaceError(409, "Materialization object partition is incomplete or duplicated")
    offset = 0
    first = pages[0]
    base = {k: v for k, v in first["query"].items() if k != "offset"}
    common = {k: v for k, v in first["metadata"].items() if k not in VALUES}
    flattened = []
    projected = {k: [] for k in VALUES if k in first["metadata"]}
    for index, page in enumerate(pages):
        query = ObjectSetQuery.model_validate(page["query"])
        pins = page["object_pins"]
        if (
            page["page_hash"] != page_hash(page, conn)
            or query.offset != offset
            or {k: v for k, v in page["query"].items() if k != "offset"} != base
            or query.valid_at is None
            or query.known_at is None
            or page["total"] != len(objects)
            or len(pins) > query.limit
            or set(page["metadata"]) != set(first["metadata"])
            or {k: v for k, v in page["metadata"].items() if k not in VALUES} != common
        ):
            raise WorkspaceError(409, "Materialization page context or hash is inconsistent")
        offset += len(pins)
        expected = offset if index < len(pages) - 1 else None
        if page["next_offset"] != expected or (expected is not None and len(pins) != query.limit):
            raise WorkspaceError(409, "Materialization pages must be contiguous and exhausted")
        flattened.extend(pins)
        for key in projected:
            projected[key].extend(page["metadata"].get(key, []))
    if flattened != [pin(obj) for obj in objects] or result["query"] != first["query"]:
        raise WorkspaceError(409, "Materialization pages differ from exact retained objects")
    if any(result.get(k) != v for k, v in {**common, **projected}.items()):
        raise WorkspaceError(409, "Materialization semantic metadata differs from retained pages")
    if offset != len(objects) or (len(pages) > 1 and not pages[-1]["object_pins"]):
        raise WorkspaceError(409, "Materialization has an incomplete or redundant page")
    return material


def collect(principal, selected, request, config):
    with resource_connection(principal, repeatable_read=True) as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        conn.execute("SELECT set_config('statement_timeout','10000',true)")
        definition = ontology_definitions.definition(
            principal, UUID(selected["resource_id"]), UUID(selected["version_id"])
        )
        if pin(definition) != selected:
            raise WorkspaceError(409, "Materialization Object Set exact pin is unavailable")
        query = ObjectSetQuery.model_validate(definition["attributes"]["definition"])
        for field in ("valid_at", "known_at"):
            if getattr(query, field) is not None and getattr(query, field) != getattr(
                request, field
            ):
                raise WorkspaceError(422, "A fixed Object Set timestamp cannot be overridden")
        query = query.model_copy(
            update={
                "offset": 0,
                "limit": request.limit,
                "valid_at": query.valid_at or request.valid_at,
                "known_at": query.known_at or request.known_at,
            }
        )
        result = None
        pages = []
        while True:
            try:
                page = _query_objects(principal, query, None, conn).model_dump(mode="json")
            except QueryCanceled as exc:
                raise WorkspaceError(
                    409, "Materialization exceeded its query execution budget"
                ) from exc
            if page["total"] > min(config["max_objects"], config["max_pages"] * request.limit):
                raise WorkspaceError(409, "Object Set exceeds reviewed materialization capacity")
            entry = {k: page[k] for k in ("query", "total", "next_offset")}
            entry["object_pins"] = [pin(obj) for obj in page["objects"]]
            entry["metadata"] = {k: page[k] for k in METADATA if k in page}
            entry["page_hash"] = page_hash(entry, conn)
            pages.append(entry)
            if result is None:
                result = {**page, "objects": list(page["objects"])}
                for key in VALUES:
                    if key in page:
                        result[key] = list(page[key])
            else:
                result["objects"].extend(page["objects"])
                for key in VALUES:
                    if key in page:
                        result[key].extend(page[key])
            if page["next_offset"] is None:
                break
            if len(pages) >= config["max_pages"]:
                raise WorkspaceError(
                    409, "Object Set exceeds reviewed materialization page capacity"
                )
            query = query.model_copy(update={"offset": page["next_offset"]})
        result.update(
            next_offset=None,
            definition_id=selected["resource_id"],
            definition_version_id=selected["version_id"],
        )
        result["materialization"] = {
            "contract": "bounded-object-set-materialization/1",
            "coverage": "COMPLETE_BOUNDED_MATERIALIZATION",
            "hash_algorithm": "POSTGRES_JSONB_TEXT_UTF8_SHA256",
            "object_set": selected,
            **config,
            "object_count": len(result["objects"]),
            "page_count": len(pages),
            "pages": pages,
        }
        validate(result, config, selected, conn)
        return result

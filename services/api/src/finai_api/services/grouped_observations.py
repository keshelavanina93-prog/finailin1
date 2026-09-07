"""Exact stored scalar grouping over complete bounded canonical observation sets."""

import json

from finai_api.services.resources import _check_scalar
from finai_api.services.workspace import WorkspaceError

SCALARS = {"text", "identifier", "reference", "integer", "boolean", "decimal", "date", "datetime"}


def validate_schema(schema: dict, fields: list[str]) -> None:
    if schema["object_type"] != "SchemaDefinition":
        raise WorkspaceError(409, "Grouping requires an exact canonical schema")
    specs = schema["attributes"]["fields"]
    if any(name not in specs or specs[name]["kind"] not in SCALARS for name in fields):
        raise WorkspaceError(422, "Grouping requires declared scalar properties")


def count_observations(result: dict, grouping: dict, schema: dict, *, materialized=False) -> dict:
    fields = grouping["fields"]
    validate_schema(schema, fields)
    objects = result["objects"]
    if (
        result["query"]["offset"] != 0
        or result["next_offset"] is not None
        or result["total"] != len(objects)
        or not 1 <= result["query"]["limit"] <= 200
        or (not materialized and len(objects) > result["query"]["limit"])
        or (materialized and ("materialization" not in result or len(objects) > 1000))
    ):
        raise WorkspaceError(409, "Observation counts require the complete bounded Object Set")
    if len({obj["resource_id"] for obj in objects}) != len(objects):
        raise WorkspaceError(409, "Observation count inputs repeat a canonical identity")
    groups: dict[str, dict] = {}
    for obj in objects:
        if (
            obj["schema_version_id"] != grouping["schema"]["version_id"]
            or obj["object_type"] != schema["identity_key"]
        ):
            raise WorkspaceError(409, "Observation schema differs from reviewed grouping schema")
        key = []
        for name in fields:
            attributes = obj["attributes"]
            spec = schema["attributes"]["fields"][name]
            state = (
                "MISSING"
                if name not in attributes
                else "NULL"
                if attributes[name] is None
                else "VALUE"
            )
            if state == "VALUE" and not _check_scalar(spec["kind"], attributes[name]):
                raise WorkspaceError(409, "Observation grouping value violates its exact schema")
            if state != "VALUE" and spec.get("required", False):
                raise WorkspaceError(409, "Observation lacks a required grouping value")
            key.append(
                {
                    "field": name,
                    "state": state,
                    **({"value": attributes[name]} if state == "VALUE" else {}),
                }
            )
        encoded = json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        group = groups.setdefault(encoded, {"key": key, "count": 0, "contributors": []})
        group["count"] += 1
        group["contributors"].append(
            {name: obj[name] for name in ("resource_id", "version_id", "content_hash")}
        )
    ordered = [groups[key] for key in sorted(groups)]
    for group in ordered:
        group["contributors"].sort(key=lambda pin: (pin["resource_id"], pin["version_id"]))
    return {
        "contract": "grouped-observation-counts/1",
        "authority": "OBSERVATION_COUNTS_ONLY",
        "coverage": "COMPLETE_BOUNDED_MATERIALIZATION"
        if materialized
        else "COMPLETE_BOUNDED_OBJECT_SET",
        "schema": grouping["schema"],
        "fields": fields,
        "object_count": len(objects),
        "groups": ordered,
    }

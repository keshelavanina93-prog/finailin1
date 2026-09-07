"""Temporal bounds describe exact retained observations, never financial period authority."""

import re
from datetime import UTC, date, datetime, timedelta

from finai_api.services.workspace import WorkspaceError

DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
INSTANT = DATE + r"T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"


def validate_schema(schema: dict, field: str) -> str:
    if schema["object_type"] != "SchemaDefinition":
        raise WorkspaceError(409, "Temporal extent requires an exact canonical schema")
    kind = schema["attributes"]["fields"].get(field, {}).get("kind")
    if kind not in {"date", "datetime"}:
        raise WorkspaceError(422, "Temporal extent requires a declared date or datetime property")
    return kind


def normalize(value: object, kind: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(DATE if kind == "date" else INSTANT, value) is None
    ):
        raise WorkspaceError(
            409, "Temporal observation requires a strict ISO value without lost precision"
        )
    try:
        if kind == "date":
            return date.fromisoformat(value).isoformat()
        if not value.endswith("Z") and (int(value[-5:-3]) > 15 or int(value[-2:]) > 59):
            raise ValueError("unsupported offset")
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
        if offset is None or abs(offset) > timedelta(hours=15, minutes=59):
            raise ValueError("unsupported offset")
        return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError) as exc:
        raise WorkspaceError(
            409, "Temporal observation is outside supported calendar or offset bounds"
        ) from exc


def extent_observations(result: dict, config: dict, schema: dict, *, materialized=False) -> dict:
    kind = validate_schema(schema, config["field"])
    if kind != config["kind"]:
        raise WorkspaceError(409, "Temporal extent kind differs from its reviewed schema")
    objects = result["objects"]
    if (
        result["query"]["offset"] != 0
        or result["next_offset"] is not None
        or result["total"] != len(objects)
        or not 1 <= result["query"]["limit"] <= 200
        or (not materialized and len(objects) > result["query"]["limit"])
        or (materialized and ("materialization" not in result or len(objects) > 1000))
    ):
        raise WorkspaceError(409, "Temporal extent requires the complete bounded Object Set")
    if len({obj["resource_id"] for obj in objects}) != len(objects):
        raise WorkspaceError(409, "Temporal inputs repeat a canonical identity")
    missing = null = 0
    values: dict[str, list[dict]] = {}
    name = config["field"]
    required = schema["attributes"]["fields"][name].get("required", False)
    for obj in objects:
        if (
            obj["schema_version_id"] != config["schema"]["version_id"]
            or obj["object_type"] != schema["identity_key"]
        ):
            raise WorkspaceError(409, "Observation schema differs from reviewed temporal schema")
        attrs = obj["attributes"]
        if name not in attrs or attrs[name] is None:
            if required:
                raise WorkspaceError(409, "Observation lacks a required temporal value")
            if name not in attrs:
                missing += 1
            else:
                null += 1
            continue
        normalized = normalize(attrs[name], kind)
        values.setdefault(normalized, []).append(
            {
                **{key: obj[key] for key in ("resource_id", "version_id", "content_hash")},
                "original_value": attrs[name],
            }
        )
    for witnesses in values.values():
        witnesses.sort(key=lambda pin: (pin["resource_id"], pin["version_id"]))

    def bound(value):
        return {"normalized_value": value, "witnesses": values[value]}

    return {
        "contract": "temporal-observation-extent/1",
        "authority": "OBSERVATION_EXTENT_ONLY",
        "coverage": "COMPLETE_BOUNDED_MATERIALIZATION"
        if materialized
        else "COMPLETE_BOUNDED_OBJECT_SET",
        "schema": config["schema"],
        "field": name,
        "kind": kind,
        "state": "AVAILABLE" if values else "NO_VALUES",
        "object_count": len(objects),
        "value_count": len(objects) - missing - null,
        "missing_count": missing,
        "null_count": null,
        "earliest": bound(min(values)) if values else None,
        "latest": bound(max(values)) if values else None,
    }

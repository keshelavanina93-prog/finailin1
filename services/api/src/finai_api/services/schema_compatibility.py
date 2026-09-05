"""Deterministic canonical schema validation and conservative compatibility evidence."""

import re
from typing import Any
from unicodedata import category
from uuid import UUID


class SchemaCompatibilityError(ValueError):
    def __init__(self, status: int, detail: str) -> None:
        self.status, self.detail = status, detail
        super().__init__(detail)


KINDS = {
    "text",
    "identifier",
    "integer",
    "decimal",
    "money",
    "quantity",
    "geometry",
    "geojson",
    "reference",
    "date",
    "datetime",
    "boolean",
}
TYPE_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{1,63}$")


def _uuid(value: Any, label: str) -> UUID:
    if not isinstance(value, str):
        raise SchemaCompatibilityError(422, f"{label} must be canonical UUID text")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise SchemaCompatibilityError(422, f"{label} must be canonical UUID text") from exc
    if str(parsed) != value:
        raise SchemaCompatibilityError(422, f"{label} must be canonical UUID text")
    return parsed


def _valid_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 256
        and not any(category(character) in {"Cc", "Cf", "Cs"} for character in value)
    )


def validate_schema(name: str, attributes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not _valid_name(name):
        raise SchemaCompatibilityError(
            422, "Schema name must be nonempty bounded text without control characters"
        )
    if type(attributes.get("additional_fields", False)) is not bool:
        raise SchemaCompatibilityError(422, "Schema additional_fields must be a boolean")
    fields = attributes.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise SchemaCompatibilityError(422, "Schema needs explicit stable fields")
    identifiers: set[UUID] = set()
    for field_name, spec in fields.items():
        if not _valid_name(field_name):
            raise SchemaCompatibilityError(
                422, "Schema field names must be nonempty bounded text without control characters"
            )
        if not isinstance(spec, dict) or not all(
            key in spec for key in ("field_id", "semantic_id", "kind", "required")
        ):
            raise SchemaCompatibilityError(422, f"Incomplete field definition: {field_name}")
        identifier = _uuid(spec["field_id"], "Field identity")
        _uuid(spec["semantic_id"], "Semantic identity")
        if identifier in identifiers:
            raise SchemaCompatibilityError(422, "Field identities must be unique within a schema")
        identifiers.add(identifier)
        if not isinstance(spec["kind"], str) or spec["kind"] not in KINDS:
            raise SchemaCompatibilityError(422, f"Unknown field value kind: {field_name}")
        if type(spec["required"]) is not bool or type(spec.get("deprecated", False)) is not bool:
            raise SchemaCompatibilityError(
                422, "Field requirement and deprecation must be booleans"
            )
        target_type = spec.get("target_type")
        if target_type is not None and (
            spec["kind"] != "reference"
            or not isinstance(target_type, str)
            or (target_type != "*" and TYPE_NAME.fullmatch(target_type) is None)
        ):
            raise SchemaCompatibilityError(422, f"Invalid canonical reference target: {field_name}")
    return fields


def schema_compatibility(
    name: str, attributes: dict[str, Any], previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    fields = validate_schema(name, attributes)
    old = validate_schema(name, previous) if previous is not None else {}
    changes: list[dict[str, Any]] = []
    breaking: set[str] = set()

    def change(field_name: str, field_id: str | None, kind: str, before: Any, after: Any) -> None:
        changes.append(
            {
                "field_id": field_id,
                "field_name": field_name,
                "change": kind,
                "before": before,
                "after": after,
            }
        )

    for field_name in sorted(set(old) | set(fields)):
        before, after = old.get(field_name), fields.get(field_name)
        if before is None:
            assert after is not None
            change(field_name, after["field_id"], "FIELD_ADDED", None, after)
            if previous is not None and after["required"]:
                breaking.add(field_name)
            continue
        if after is None:
            change(field_name, before["field_id"], "FIELD_REMOVED", before, None)
            breaking.add(field_name)
            continue
        for key, kind in (
            ("field_id", "FIELD_ID_CHANGED"),
            ("semantic_id", "SEMANTIC_CHANGED"),
            ("kind", "VALUE_KIND_CHANGED"),
            ("target_type", "TARGET_TYPE_CHANGED"),
        ):
            if before.get(key) != after.get(key):
                change(field_name, before["field_id"], kind, before.get(key), after.get(key))
                breaking.add(field_name)
        if before["required"] != after["required"]:
            change(
                field_name,
                before["field_id"],
                "REQUIRED_TIGHTENED" if after["required"] else "REQUIRED_LOOSENED",
                before["required"],
                after["required"],
            )
            if after["required"]:
                breaking.add(field_name)
        if before.get("deprecated", False) != after.get("deprecated", False):
            change(
                field_name,
                before["field_id"],
                "DEPRECATED" if after.get("deprecated", False) else "UNDEPRECATED",
                before.get("deprecated", False),
                after.get("deprecated", False),
            )
        semantic_keys = {"field_id", "semantic_id", "kind", "target_type", "required", "deprecated"}
        if any(
            before.get(key) != after.get(key) for key in (set(before) | set(after)) - semantic_keys
        ):
            change(field_name, before["field_id"], "FIELD_METADATA_CHANGED", before, after)
    prior_additional = previous.get("additional_fields", False) if previous is not None else None
    next_additional = attributes.get("additional_fields", False)
    if prior_additional != next_additional:
        kind = (
            "ADDITIONAL_FIELDS_POLICY"
            if previous is None
            else ("ADDITIONAL_FIELDS_ENABLED" if next_additional else "ADDITIONAL_FIELDS_DISABLED")
        )
        change("additional_fields", None, kind, prior_additional, next_additional)
    if prior_additional is True and next_additional is False:
        breaking.add("additional_fields (unknown-field narrowing)")
    if breaking:
        raise SchemaCompatibilityError(
            409,
            "Incompatible schema evolution requires an explicit "
            "migration change set: " + ", ".join(sorted(breaking)),
        )
    return {
        "compatibility": "INITIAL" if previous is None else "BACKWARD_COMPATIBLE",
        "semantic_changes": changes,
    }

"""Explicit interface projections of canonical resource metadata, never business fields."""

from typing import Any

METADATA_FIELDS: dict[str, dict[str, Any]] = {
    "resource_id": {"kind": "identifier", "required": True},
    "object_type": {"kind": "identifier", "required": True},
    "tenant_id": {"kind": "identifier", "required": True},
    "version_id": {"kind": "identifier", "required": True},
    "display_name": {"kind": "text", "required": True},
    "authority_state": {"kind": "identifier", "required": True},
    "evidence_class": {"kind": "identifier", "required": True},
    "valid_from": {"kind": "datetime", "required": True},
    "valid_to": {"kind": "datetime", "required": False},
    "system_from": {"kind": "datetime", "required": True},
}


def metadata_spec(field: str) -> dict[str, Any] | None:
    return METADATA_FIELDS.get(field.removeprefix("meta:")) if field.startswith("meta:") else None


def interface_value(resource: dict[str, Any], field: str) -> Any:
    if metadata_spec(field) is None:
        return resource["attributes"].get(field)
    value = resource.get(field.removeprefix("meta:"))
    return str(value) if value is not None else None

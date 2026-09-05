"""Deterministic review facts, retained with the proposal rather than recomputed from heads."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from finai_api.domain.resources import ResourceMutation


def _json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


def semantic_diff(
    previous: dict[str, Any] | None, proposed: ResourceMutation, access_entity: str
) -> dict[str, Any]:
    """Compare meaning-bearing fields with explicit presence, types and JSON-pointer paths.

    Arrays remain atomic because their ordering can have business meaning. Null is never
    equated with a missing property, nor a boolean with a numeric value.
    """
    fields = (
        "object_type",
        "identity_key",
        "access_entity",
        "display_name",
        "valid_from",
        "valid_to",
        "authority_state",
        "evidence_class",
        "attributes",
    )
    before = {key: _json(previous[key]) for key in fields} if previous else {}
    after = {key: _json(getattr(proposed, key)) for key in fields}
    after["access_entity"] = access_entity
    changes: list[dict[str, Any]] = []

    def category(path: list[str]) -> str:
        root = path[0]
        if root in {"object_type", "identity_key", "access_entity"}:
            return "IDENTITY_AND_ACCESS"
        if root in {"authority_state", "evidence_class"}:
            return "AUTHORITY_AND_EVIDENCE"
        if root in {"valid_from", "valid_to"}:
            return "EFFECTIVE_TIME"
        if root == "display_name":
            return "PRESENTATION"
        if proposed.object_type in {"SchemaDefinition", "SemanticContract", "LinkType"}:
            return "SEMANTIC_CONTRACT"
        if path[-1].endswith(("_id", "_ids")):
            return "CANONICAL_REFERENCE"
        return "BUSINESS_PROPERTY"

    def visit(old: Any, new: Any, path: list[str], old_exists: bool, new_exists: bool) -> None:
        if old_exists and new_exists and isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                visit(old.get(key), new.get(key), [*path, key], key in old, key in new)
            return
        if old_exists == new_exists and json.dumps(old, sort_keys=True) == json.dumps(
            new, sort_keys=True
        ):
            return
        changes.append(
            {
                "path": "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path),
                "category": category(path),
                "operation": "ADD" if not old_exists else "REMOVE" if not new_exists else "CHANGE",
                "before": {"present": old_exists, **({"value": old} if old_exists else {})},
                "after": {"present": new_exists, **({"value": new} if new_exists else {})},
            }
        )

    for key in fields:
        visit(before.get(key), after[key], [key], key in before, True)
    return {
        "format_version": 1,
        "base_version_id": str(previous["version_id"]) if previous else None,
        "changes": changes,
    }

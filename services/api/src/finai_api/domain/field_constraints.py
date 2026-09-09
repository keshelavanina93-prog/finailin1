"""Bounded executable field constraints shared by catalog and resource publication."""

import json
import re
from typing import Any


def validate_constraints(spec: Any, depth: int = 0) -> None:
    if not isinstance(spec, dict) or depth > 4:
        raise ValueError("Field constraints must be a bounded object")
    if set(spec) - {"type", "enum", "const", "pattern", "items", "maxItems"}:
        raise ValueError("Unsupported field constraint")
    if "type" in spec and spec["type"] not in {"array", "object", "string"}:
        raise ValueError("Unsupported constrained value type")
    if "enum" in spec and (
        not isinstance(spec["enum"], list)
        or not 1 <= len(spec["enum"]) <= 100
        or any(not isinstance(v, str) or len(v) > 256 for v in spec["enum"])
        or len(set(spec["enum"])) != len(spec["enum"])
    ):
        raise ValueError("Enumeration must contain distinct bounded strings")
    if "const" in spec and (not isinstance(spec["const"], str) or len(spec["const"]) > 256):
        raise ValueError("Constant must be bounded text")
    if "pattern" in spec:
        pattern = spec["pattern"]
        if (
            not isinstance(pattern, str)
            or len(pattern) > 128
            or any(token in pattern for token in ("(", ")", "|", "\\1", "\\2"))
        ):
            raise ValueError("Pattern must use bounded simple character expressions")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError("Invalid field pattern") from exc
    if "items" in spec:
        if spec.get("type") != "array":
            raise ValueError("Items require an array constraint")
        validate_constraints(spec["items"], depth + 1)
    if "maxItems" in spec and (
        spec.get("type") != "array"
        or type(spec["maxItems"]) is not int
        or not 1 <= spec["maxItems"] <= 1000
    ):
        raise ValueError("Array limit must be between one and 1000")


def matches_constraints(value: Any, spec: dict[str, Any]) -> bool:
    if "enum" in spec and value not in spec["enum"]:
        return False
    if "const" in spec and value != spec["const"]:
        return False
    if "pattern" in spec and (
        not isinstance(value, str)
        or len(value) > 2000
        or re.fullmatch(spec["pattern"], value) is None
    ):
        return False
    kind = spec.get("type")
    if kind == "string" and not isinstance(value, str):
        return False
    if kind == "object" and not isinstance(value, dict):
        return False
    if kind == "array":
        if not isinstance(value, list) or len(value) > spec.get("maxItems", 1000):
            return False
        if not all(matches_constraints(item, spec.get("items", {})) for item in value):
            return False
    try:
        return len(json.dumps(value, allow_nan=False)) <= 100000
    except (ValueError, TypeError, RecursionError):
        return False

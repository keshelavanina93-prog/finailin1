"""Filter values obey the same scalar contracts as canonical resource properties."""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from finai_api.domain.object_sets import PropertyFilter
from finai_api.services.resources import _check_scalar
from finai_api.services.workspace import WorkspaceError

RANGE_PATTERNS = {
    "decimal": r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
    "date": r"[0-9]{4}-[0-9]{2}-[0-9]{2}",
    "datetime": (
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
    ),
}


def validate_filters(filters: list[PropertyFilter], fields: dict[str, Any]) -> None:
    for condition in filters:
        spec = fields.get(condition.field)
        if spec is None:
            raise WorkspaceError(422, "Object Set filter references an undeclared property")
        if condition.operator != "eq":
            kind = spec["kind"]
            if (
                kind not in {"integer", "decimal", "date", "datetime"}
                or condition.value is None
                or isinstance(condition.value, bool)
            ):
                raise WorkspaceError(
                    422, "Range filters require a declared numeric or temporal property"
                )
            if kind in RANGE_PATTERNS and (
                not isinstance(condition.value, str)
                or re.fullmatch(RANGE_PATTERNS[kind], condition.value) is None
            ):
                raise WorkspaceError(
                    422, "Range values require exact decimal or strict ISO temporal values"
                )
        if condition.value is None:
            valid = not spec.get("required", False)
        else:
            valid = _check_scalar(spec["kind"], condition.value)
        if not valid:
            raise WorkspaceError(
                422, f"Filter {condition.field} requires a canonical {spec['kind']} value"
            )
        if condition.operator != "eq" and spec["kind"] == "decimal":
            parts = Decimal(str(condition.value)).as_tuple()
            exponent = int(parts.exponent)
            if len(parts.digits) + exponent > 131072 or -exponent > 16383:
                raise WorkspaceError(422, "Range threshold exceeds exact numeric representation")
        if condition.operator != "eq" and spec["kind"] == "datetime":
            offset = datetime.fromisoformat(str(condition.value)).utcoffset()
            if offset is None or abs(offset) > timedelta(hours=15, minutes=59):
                raise WorkspaceError(422, "Range timestamp offset exceeds supported representation")

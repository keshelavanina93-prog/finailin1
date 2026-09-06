"""Filter values obey the same scalar contracts as canonical resource properties."""

from typing import Any

from finai_api.domain.object_sets import PropertyFilter
from finai_api.services.resources import _check_scalar
from finai_api.services.workspace import WorkspaceError


def validate_filters(filters: list[PropertyFilter], fields: dict[str, Any]) -> None:
    for condition in filters:
        spec = fields.get(condition.field)
        if spec is None:
            raise WorkspaceError(422, "Object Set filter references an undeclared property")
        if condition.value is None:
            valid = not spec.get("required", False)
        else:
            valid = _check_scalar(spec["kind"], condition.value)
        if not valid:
            raise WorkspaceError(
                422, f"Filter {condition.field} requires a canonical {spec['kind']} value"
            )

"""Deterministic aggregation of one versioned fact representation at a declared grain."""

import json
from datetime import date
from decimal import Decimal, DecimalException, Inexact, InvalidOperation, localcontext
from typing import Any
from uuid import UUID

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_definitions import FactContract
from finai_api.domain.review import Principal
from finai_api.services.object_sets import query_objects
from finai_api.services.ontology_definitions import definition
from finai_api.services.workspace import WorkspaceError


def aggregate_rows(
    spec: FactContract,
    rows: list[dict[str, Any]],
    schema_version: str,
    group_by: list[str],
    as_of: date | None,
) -> list[dict[str, Any]]:
    if len(set(group_by)) != len(group_by) or not set(group_by).issubset(spec.dimensions):
        raise WorkspaceError(422, "Grouping requires distinct declared dimensions")
    if spec.aggregation == "closing_balance" and as_of is None:
        raise WorkspaceError(422, "Closing balances require an explicit as-of date")
    # Currency/unit is always a grouping key: unlike totals cannot be silently added.
    keys = list(dict.fromkeys([*group_by, spec.unit_field]))
    seen: set[str] = set()
    groups: dict[str, dict[str, Any]] = {}
    with localcontext() as context:
        context.prec = 50
        context.traps[Inexact] = True
        for row in rows:
            if str(row["schema_version_id"]) != schema_version:
                raise WorkspaceError(409, "Fact schema differs from the contract's pinned version")
            if row["evidence_class"] != "SOURCE_BOUND":
                raise WorkspaceError(
                    422, "Reference and user-asserted rows cannot enter source-backed aggregation"
                )
            values = row["attributes"]
            if values.get(spec.source_family_field) != spec.source_family:
                raise WorkspaceError(
                    422, "Query mixes representations outside this contract's source family"
                )
            if any(values.get(field) is None for field in [*spec.grain, spec.measure]):
                raise WorkspaceError(
                    422, "Missing grain or measure; missing values cannot become zero"
                )
            grain = json.dumps([values[field] for field in spec.grain], sort_keys=True)
            if grain in seen:
                raise WorkspaceError(
                    409, "Duplicate fact grain; reconcile overlapping sources before aggregation"
                )
            seen.add(grain)
            if spec.aggregation == "closing_balance":
                assert as_of is not None
                observed_date = str(values[spec.time_field])[:10]
                if observed_date != as_of.isoformat():
                    raise WorkspaceError(
                        422, "Closing-balance query must contain only the requested snapshot date"
                    )
            try:
                amount = Decimal(str(values[spec.measure]))
                if not amount.is_finite():
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise WorkspaceError(422, "Fact contains a non-finite or invalid measure") from exc
            coordinates = {field: values[field] for field in keys}
            key = json.dumps(coordinates, sort_keys=True)
            group = groups.setdefault(
                key, {"dimensions": coordinates, "value": Decimal(0), "inputs": []}
            )
            if spec.aggregation == "non_additive" and group["inputs"]:
                raise WorkspaceError(
                    422, "Non-additive measures require their explicit calculation function"
                )
            try:
                group["value"] += amount
            except DecimalException as exc:
                raise WorkspaceError(422, "Aggregation exceeds exact numeric precision") from exc
            group["inputs"].append(
                {"resource_id": row["resource_id"], "version_id": row["version_id"]}
            )
        return [
            {**group, "value": format(group["value"], "f")} for _, group in sorted(groups.items())
        ]


def aggregate_facts(
    principal: Principal,
    identity: UUID,
    query: ObjectSetQuery,
    group_by: list[str],
    as_of: date | None,
) -> dict[str, Any]:
    resource = definition(principal, identity)
    if resource["object_type"] != "FactContract":
        raise WorkspaceError(422, "Aggregation requires an accepted Fact Contract")
    spec = FactContract.model_validate(resource["attributes"]["definition"])
    schema = next((p for p in resource["dependencies"] if p["relation"] == "FIELD:schema_id"), None)
    if schema is None:
        raise WorkspaceError(409, "Fact schema dependency unavailable")
    if query.object_type != schema["identity_key"] or query.traversal:
        raise WorkspaceError(
            422, "Aggregate one fact type directly; traversals are not financial joins"
        )
    result = query_objects(principal, query.model_copy(update={"offset": 0, "limit": 200}))
    if result.total > 10000:
        raise WorkspaceError(
            422, "This interactive aggregation supports 10000 facts; narrow the query"
        )
    rows = list(result.objects)
    while result.next_offset is not None:
        result = query_objects(
            principal, result.query.model_copy(update={"offset": result.next_offset})
        )
        rows.extend(result.objects)
        if len(rows) > 10000:
            raise WorkspaceError(409, "Result changed during aggregation; retry the query")
    groups = aggregate_rows(spec, rows, str(schema["version_id"]), group_by, as_of)
    return {
        "contract_id": identity,
        "contract_version_id": resource["version_id"],
        "query": result.query.model_copy(update={"offset": 0}).model_dump(mode="json"),
        "aggregation": spec.aggregation,
        "as_of": as_of,
        "groups": groups,
        "input_count": len(rows),
        "state": "DERIVED" if rows else "UNAVAILABLE",
        "authority": "SOURCE_BOUND_ANALYSIS",
        "financial_certification": None,
    }

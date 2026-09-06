"""Deterministic aggregation of one versioned fact representation at a declared grain."""

import json
from datetime import date
from decimal import (
    ROUND_HALF_EVEN,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    localcontext,
)
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
    snapshot = spec.aggregation in {"closing_balance", "cumulative_snapshot"}
    if snapshot and as_of is None:
        raise WorkspaceError(422, "Balances and cumulative values require an explicit as-of date")
    # Currency/unit is always a grouping key: unlike totals cannot be silently added.
    keys = list(dict.fromkeys([*group_by, *spec.partition_fields, spec.unit_field]))
    seen: set[str] = set()
    groups: dict[str, dict[str, Any]] = {}
    hierarchy: dict[str, set[str]] = {}
    parents: dict[str, set[str]] = {}
    with localcontext() as context:
        context.prec = 50
        context.traps[Inexact] = True
        for row in rows:
            if row.get("object_type") in {"SourceJournalMovement", "SourceTrialBalanceRow"}:
                raise WorkspaceError(
                    409,
                    "Source accounting observations require ledger, unit and representation "
                    "bindings before financial aggregation",
                )
            if str(row["schema_version_id"]) != schema_version:
                raise WorkspaceError(409, "Fact schema differs from the contract's pinned version")
            if row["evidence_class"] != "SOURCE_BOUND":
                raise WorkspaceError(
                    422, "Reference and user-asserted rows cannot enter source-backed aggregation"
                )
            values = row["attributes"]
            if spec.row_role_field and values.get(spec.row_role_field) != spec.included_row_role:
                raise WorkspaceError(
                    422, "Query includes source controls or details outside the selected row role"
                )
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
            if spec.hierarchy_key_field:
                scope = json.dumps(
                    [
                        values[f]
                        for f in dict.fromkeys(
                            [spec.time_field, spec.unit_field, *spec.partition_fields]
                        )
                    ],
                    sort_keys=True,
                )
                fact_key = str(values[spec.hierarchy_key_field])
                members = hierarchy.setdefault(scope, set())
                if fact_key in members:
                    raise WorkspaceError(409, "Hierarchy identity is not unique in this scope")
                members.add(fact_key)
                parent = values.get(spec.parent_key_field)
                if parent is not None:
                    parents.setdefault(scope, set()).add(str(parent))
            if snapshot:
                assert as_of is not None
                observed_date = str(values[spec.time_field])[:10]
                if observed_date != as_of.isoformat():
                    raise WorkspaceError(
                        422,
                        "Balance/cumulative query must contain only the requested snapshot date",
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
                if spec.denominator_measure:
                    denominator = Decimal(str(values.get(spec.denominator_measure)))
                    if not denominator.is_finite():
                        raise InvalidOperation
                    group["denominator"] = group.get("denominator", Decimal(0)) + denominator
            except DecimalException as exc:
                raise WorkspaceError(422, "Aggregation exceeds exact numeric precision") from exc
            group["inputs"].append(
                {"resource_id": row["resource_id"], "version_id": row["version_id"]}
            )
        if any(
            members.intersection(parents.get(scope, set())) for scope, members in hierarchy.items()
        ):
            raise WorkspaceError(409, "Parent and child representations cannot be added together")
        output = []
        for _, group in sorted(groups.items()):
            if spec.aggregation == "ratio_of_sums":
                numerator, denominator = group["value"], group.pop("denominator")
                group["components"] = {
                    "numerator": format(numerator, "f"),
                    "denominator": format(denominator, "f"),
                }
                group["rounding"] = {"mode": "HALF_EVEN", "scale": spec.ratio_scale}
                if denominator == 0:
                    group.update(value=None, state="UNAVAILABLE", reason="ZERO_DENOMINATOR")
                else:
                    with localcontext() as ratio_context:
                        ratio_context.traps[Inexact] = False
                        try:
                            value = (numerator * spec.ratio_multiplier / denominator).quantize(
                                Decimal(1).scaleb(-spec.ratio_scale), rounding=ROUND_HALF_EVEN
                            )
                        except DecimalException as exc:
                            raise WorkspaceError(422, "Ratio exceeds numeric precision") from exc
                    group.update(value=format(value, "f"), state="DERIVED")
            else:
                group["value"] = format(group["value"], "f")
            output.append(group)
        return output


def aggregate_facts(
    principal: Principal,
    identity: UUID,
    query: ObjectSetQuery,
    group_by: list[str],
    as_of: date | None,
    expected_contract_version: UUID | None = None,
) -> dict[str, Any]:
    resource = definition(principal, identity)
    if expected_contract_version and str(resource["version_id"]) != str(expected_contract_version):
        raise WorkspaceError(409, "Fact contract changed during reconciliation")
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
        "state": "UNAVAILABLE"
        if not rows
        else ("INCOMPLETE" if any(g.get("state") == "UNAVAILABLE" for g in groups) else "DERIVED"),
        "authority": "SOURCE_BOUND_ANALYSIS",
        "financial_certification": None,
    }

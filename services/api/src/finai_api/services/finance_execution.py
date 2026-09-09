"""Deterministic finance adapters; all retained evidence uses the existing fact-run store."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException, Inexact, localcontext
from typing import Any, Literal
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.finance_execution import (
    CanonicalJournalTrialBalanceRequest,
    FinanceCalculation,
    FinanceExecutionRequest,
    FinanceProjectionDefinition,
)
from finai_api.domain.ontology_definitions import FactContract
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import fact_runs, ontology_definitions
from finai_api.services.certification import _current
from finai_api.services.fact_aggregation import aggregate_rows
from finai_api.services.object_sets import query_objects
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError

OPERATIONS = ("trial_balance", "closing_as_of", "ytd_flow", "reconcile_parent", "project")


def projection_references(spec: FinanceProjectionDefinition):
    """The publication compiler and executor use the same nested dependency names."""
    roots = [
        ("fact_contract", spec.fact_contract, "FactContract"),
        ("company", spec.company, "LegalEntity"),
        ("chart", spec.chart, "LocalChartOfAccounts"),
        ("evidence", spec.evidence, "SourceEvidence"),
    ]
    seen = set()
    for rule in spec.rules:
        for role, ref, kind in (
            ("account", rule.account, "LocalAccount"),
            ("reporting_line", rule.reporting_line, "ReportingLine"),
        ):
            key = (role, ref.resource_id, ref.version_id)
            if key not in seen:
                roots.append((role, ref, kind))
                seen.add(key)
    for role, ref, kind in roots:
        yield "FINANCE_PROJECTION:" + role + ":" + str(ref.resource_id), ref, kind


def validate_projection(item: ResourceMutation, target: Callable[..., dict]) -> None:
    """Called by canonical definition publication, never a separate approval path."""
    spec = FinanceProjectionDefinition.model_validate(item.attributes["definition"])
    if item.access_entity != spec.exact_scope.legal_entity_id:
        raise WorkspaceError(409, "Projection must belong to its declared company access scope")
    selected = {}
    for relation, ref, kind in projection_references(spec):
        row = target(str(ref.resource_id), str(item.resource_id), relation, str(ref.version_id))
        if (
            row["object_type"] != kind
            or str(row["version_id"]) != str(ref.version_id)
            or row.get("authority_state") != "APPROVED"
        ):
            raise WorkspaceError(409, "Projection requires exact reviewed dependency versions")
        if row.get("access_entity") != spec.exact_scope.legal_entity_id:
            raise WorkspaceError(409, "Projection dependency belongs to another company scope")
        selected[str(ref.resource_id)] = row
    chart = selected[str(spec.chart.resource_id)]
    if str(chart["attributes"].get("legal_entity_id")) != str(spec.company.resource_id):
        raise WorkspaceError(409, "Projection chart does not belong to the selected company")
    for rule in spec.rules:
        account = selected[str(rule.account.resource_id)]
        if str(account["attributes"].get("chart_id")) != str(spec.chart.resource_id):
            raise WorkspaceError(409, "Projection account does not belong to the selected chart")
    fact = FactContract.model_validate(
        selected[str(spec.fact_contract.resource_id)]["attributes"]["definition"]
    )
    if spec.account_field not in fact.dimensions or fact.source_family != spec.source_family:
        raise WorkspaceError(409, "Projection source family/account differs from its fact contract")
    if fact.aggregation != "flow_sum":
        raise WorkspaceError(422, "Finance report projections require a flow representation")


def _pin(row: dict) -> dict:
    return {
        "resource_id": str(row["resource_id"]),
        "version_id": str(row["version_id"]),
        **({"content_hash": row["content_hash"]} if "content_hash" in row else {}),
    }


def _date(value: Any) -> date:
    if not isinstance(value, str):
        raise WorkspaceError(422, "Finance dates must be canonical calendar-date strings")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise WorkspaceError(422, "Finance input contains an invalid calendar date") from exc
    if value != result.isoformat():
        raise WorkspaceError(422, "Finance dates must use YYYY-MM-DD")
    return result


def _decimal(value: Any) -> Decimal:
    if not isinstance(value, str) or len(value) > 100:
        raise WorkspaceError(422, "Finance measures require bounded exact decimal strings")
    try:
        result = Decimal(value)
        if not result.is_finite() or abs(result.adjusted()) > 48:
            raise ValueError("Non-finite or excessive exponent")
    except (ValueError, DecimalException) as exc:
        raise WorkspaceError(422, "Finance measure is invalid or exceeds exact precision") from exc
    return result


def _preflight(spec: FactContract, rows: list[dict], request: FinanceExecutionRequest):
    if request.account_field not in spec.dimensions:
        raise WorkspaceError(422, "Finance execution requires a declared account dimension")
    if not set(request.group_by).issubset(spec.dimensions):
        raise WorkspaceError(422, "Finance grouping requires declared dimensions")
    refs = set()
    for row in rows:
        ref = (str(row["resource_id"]), str(row["version_id"]))
        if ref in refs:
            raise WorkspaceError(409, "Finance input repeats an exact source version")
        refs.add(ref)
        # Validate UUID provenance before calculations; unretained ad-hoc rows cannot
        # accidentally masquerade as canonical source references in a result.
        VersionReference(resource_id=UUID(ref[0]), version_id=UUID(ref[1]))
        values = row["attributes"]
        for field in [*spec.grain, spec.measure]:
            if values.get(field) is None:
                raise WorkspaceError(422, "Missing grain or measure; missing is not zero")
        _decimal(values[spec.measure])
        end = _date(values[spec.time_field])
        if end > request.as_of or (request.starts_on and end < request.starts_on):
            raise WorkspaceError(422, "Selected facts fall outside requested coverage")
        if spec.period_start_field:
            start = _date(values[spec.period_start_field])
            if start > end or (request.starts_on and start < request.starts_on):
                raise WorkspaceError(422, "Selected fact interval crosses requested coverage")


def _period_coverage(spec: FactContract, rows: list[dict], request: FinanceExecutionRequest):
    """An empty period is unknown unless an explicit source interval supplies its zero."""
    if spec.period_start_field is None:
        return {}
    intervals: dict[str, list[tuple[date, date]]] = {}
    identity_fields = [
        field for field in spec.grain if field not in {spec.time_field, spec.period_start_field}
    ]
    for row in rows:
        values = row["attributes"]
        key = json.dumps({field: values[field] for field in identity_fields}, sort_keys=True)
        intervals.setdefault(key, []).append(
            (_date(values[spec.period_start_field]), _date(values[spec.time_field]))
        )
    missing = {}
    for key, periods in intervals.items():
        cursor = request.starts_on
        issues = []
        for start, end in sorted(periods):
            if cursor is not None and start < cursor:
                raise WorkspaceError(409, "Overlapping accounting periods cannot be accumulated")
            if cursor is not None and start > cursor:
                issues.append(f"MISSING_INTERVAL:{cursor}:{start - timedelta(days=1)}")
            cursor = end + timedelta(days=1)
        if cursor is not None and cursor <= request.as_of:
            issues.append(f"MISSING_INTERVAL:{cursor}:{request.as_of}")
        if issues:
            missing[key] = issues
    return missing


def _apply_coverage(groups, spec, rows, missing):
    by_ref = {(str(row["resource_id"]), str(row["version_id"])): row for row in rows}
    identity_fields = [
        field for field in spec.grain if field not in {spec.time_field, spec.period_start_field}
    ]
    for group in groups:
        issues = set()
        for ref in group["inputs"]:
            values = by_ref[(str(ref["resource_id"]), str(ref["version_id"]))]["attributes"]
            key = json.dumps({field: values[field] for field in identity_fields}, sort_keys=True)
            issues.update(missing.get(key, []))
        if issues:
            group.update(
                observed_value=group["value"],
                value=None,
                state="INCOMPLETE",
                missing=sorted(issues),
            )


def _trial_balance(spec, rows, schema_version, request):
    if spec.aggregation != "flow_sum" or spec.period_start_field:
        raise WorkspaceError(422, "Journal turnover requires individual flow postings")
    if request.side_field is None or request.side_field not in spec.dimensions:
        raise WorkspaceError(422, "Trial balance requires a declared posting-side dimension")
    if request.side_field in request.group_by or request.side_field in spec.partition_fields:
        raise WorkspaceError(422, "Posting side is combined into debit and credit turnover")
    grouping = list(dict.fromkeys([request.account_field, *request.group_by, request.side_field]))
    for row in rows:
        values = row["attributes"]
        if values[request.side_field] not in {"DEBIT", "CREDIT", "DR", "CR"}:
            raise WorkspaceError(422, "Journal side must explicitly identify debit or credit")
        if _decimal(values[spec.measure]) < 0:
            raise WorkspaceError(422, "Side-based journal amounts must be non-negative")
    observed = aggregate_rows(spec, rows, schema_version, grouping, None)
    groups = {}
    for group in observed:
        dimensions = {k: v for k, v in group["dimensions"].items() if k != request.side_field}
        key = json.dumps(dimensions, sort_keys=True)
        output = groups.setdefault(
            key, {"dimensions": dimensions, "debit": Decimal(0), "credit": Decimal(0), "inputs": []}
        )
        side = "debit" if group["dimensions"][request.side_field] in {"DR", "DEBIT"} else "credit"
        output[side] += _decimal(group["value"])
        output["inputs"].extend(group["inputs"])
    return [
        {
            "dimensions": group["dimensions"],
            "value": format(group["debit"] - group["credit"], "f"),
            "debit_turnover": format(group["debit"], "f"),
            "credit_turnover": format(group["credit"], "f"),
            "inputs": group["inputs"],
            "missing": ["OPENING_BALANCE_NOT_SUPPLIED", "CLOSING_BALANCE_NOT_DERIVABLE"],
        }
        for _, group in sorted(groups.items())
    ]


def _parents(spec, rows, schema_version, request):
    if not spec.hierarchy_key_field or not spec.parent_key_field:
        raise WorkspaceError(422, "Parent reconciliation requires an explicit hierarchy contract")
    if spec.aggregation in {"ratio_of_sums", "non_additive"}:
        raise WorkspaceError(422, "Parent reconciliation requires additive measures")
    # Validate every row under its original contract, then compare independent
    # parent/control values with child values; never aggregate the two together.
    for row in rows:
        aggregate_rows(spec, [row], schema_version, [], request.as_of)
    context_fields = list(
        dict.fromkeys(
            [
                spec.time_field,
                *([spec.period_start_field] if spec.period_start_field else []),
                *spec.partition_fields,
                spec.unit_field,
                *request.group_by,
            ]
        )
    )
    context_fields = [field for field in context_fields if field != spec.hierarchy_key_field]
    observed, children = {}, {}
    for row in rows:
        values = row["attributes"]
        scope = json.dumps({key: values[key] for key in context_fields}, sort_keys=True)
        key = (scope, str(values[spec.hierarchy_key_field]))
        if key in observed:
            raise WorkspaceError(409, "Parent reconciliation requires one value per hierarchy node")
        observed[key] = row
        parent = values.get(spec.parent_key_field)
        if parent is not None:
            children.setdefault((scope, str(parent)), []).append(row)
    for key in observed:
        seen, cursor = set(), key
        while cursor in observed:
            if cursor in seen:
                raise WorkspaceError(409, "Parent reconciliation hierarchy contains a cycle")
            seen.add(cursor)
            parent = observed[cursor]["attributes"].get(spec.parent_key_field)
            if parent is None:
                break
            cursor = (cursor[0], str(parent))
    result = []
    for key, members in sorted(children.items()):
        parent = observed.get(key)
        child_total = sum(
            (_decimal(row["attributes"][spec.measure]) for row in members), Decimal(0)
        )
        parent_value = _decimal(parent["attributes"][spec.measure]) if parent else None
        difference = parent_value - child_total if parent_value is not None else None
        result.append(
            {
                "dimensions": {**json.loads(key[0]), spec.hierarchy_key_field: key[1]},
                "state": "MISSING_PARENT"
                if parent is None
                else "MATCHED"
                if difference == 0
                else "DIFFERENCE",
                "parent_value": format(parent_value, "f") if parent_value is not None else None,
                "child_value": format(child_total, "f"),
                "difference": format(difference, "f") if difference is not None else None,
                "parent": _pin(parent) if parent else None,
                "children": [_pin(row) for row in members],
                "coverage": "OBSERVED_CHILDREN_ONLY",
            }
        )
    return result


def _project(spec, rows, schema_version, request, projection):
    if projection is None:
        raise WorkspaceError(409, "Projection execution requires a reviewed definition")
    if (
        projection.fact_contract != request.contract
        or projection.source_family != spec.source_family
        or projection.account_field != request.account_field
        or projection.starts_on != request.starts_on
        or projection.ends_on != request.as_of
        or spec.aggregation != "flow_sum"
    ):
        raise WorkspaceError(409, "Projection differs from the exact fact contract or coverage")
    if request.account_field in request.group_by:
        raise WorkspaceError(422, "Projection replaces its account dimension with reporting line")
    if request.account_field in spec.partition_fields:
        raise WorkspaceError(422, "Projection cannot remove a mandatory account partition")
    if any(str(row["attributes"][spec.unit_field]) != projection.unit_value for row in rows):
        raise WorkspaceError(
            409, "Projection cannot mix currency/unit values outside its reviewed policy"
        )
    grouping = list(dict.fromkeys([request.account_field, *request.group_by]))
    groups = aggregate_rows(spec, rows, schema_version, grouping, None)
    _apply_coverage(groups, spec, rows, _period_coverage(spec, rows, request))
    rules = {str(rule.account.resource_id): rule for rule in projection.rules}
    present = {str(group["dimensions"][request.account_field]) for group in groups}
    missing, unmapped = sorted(rules.keys() - present), sorted(present - rules.keys())
    partition_members = {}
    for group in groups:
        coordinates = {
            name: group["dimensions"][name] for name in [*spec.partition_fields, spec.unit_field]
        }
        partition_members.setdefault(json.dumps(coordinates, sort_keys=True), set()).add(
            str(group["dimensions"][request.account_field])
        )
    projected = {}
    for group in groups:
        account = str(group["dimensions"][request.account_field])
        if account not in rules:
            continue
        rule = rules[account]
        dimensions = {k: v for k, v in group["dimensions"].items() if k != request.account_field}
        dimensions.update(
            projection_code=projection.projection_code,
            reporting_line_id=str(rule.reporting_line.resource_id),
        )
        key = json.dumps(dimensions, sort_keys=True)
        output = projected.setdefault(
            key,
            {
                "dimensions": dimensions,
                "observed": Decimal(0),
                "inputs": [],
                "missing": set(),
            },
        )
        value = group["value"] if group["value"] is not None else group["observed_value"]
        output["observed"] += _decimal(value) * Decimal(rule.multiplier)
        output["inputs"].extend(group["inputs"])
        output["missing"].update(group.get("missing", []))
        coordinates = {
            name: group["dimensions"][name] for name in [*spec.partition_fields, spec.unit_field]
        }
        partition_missing = (
            rules.keys() - partition_members[json.dumps(coordinates, sort_keys=True)]
        )
        output["missing"].update("MISSING_ACCOUNT:" + identity for identity in partition_missing)
        output["missing"].update("UNMAPPED_ACCOUNT:" + identity for identity in unmapped)
    output_groups = []
    for _, group in sorted(projected.items()):
        observed = format(group["observed"], "f")
        issues = sorted(group["missing"])
        output_groups.append(
            {
                "dimensions": group["dimensions"],
                "value": None if issues else observed,
                "observed_value": observed if issues else None,
                "state": "INCOMPLETE" if issues else "DERIVED",
                "inputs": group["inputs"],
                "missing": issues,
            }
        )
    return output_groups, missing, unmapped


def calculate(
    spec: FactContract,
    rows: list[dict],
    schema_version: str,
    request: FinanceExecutionRequest,
    projection: FinanceProjectionDefinition | None = None,
) -> FinanceCalculation:
    """Pure typed core; callers use execute() for authorized, retained resource execution."""
    _preflight(spec, rows, request)
    groups, comparisons, missing, unmapped = [], [], [], []
    try:
        with localcontext() as context:
            context.prec = 50
            context.traps[Inexact] = True
            if request.operation == "trial_balance":
                groups = _trial_balance(spec, rows, schema_version, request)
            elif request.operation == "reconcile_parent":
                comparisons = _parents(spec, rows, schema_version, request)
            elif request.operation == "project":
                groups, missing, unmapped = _project(
                    spec, rows, schema_version, request, projection
                )
            else:
                if request.operation == "closing_as_of" and spec.aggregation != "closing_balance":
                    raise WorkspaceError(422, "closing_as_of requires a closing-balance contract")
                if request.operation == "ytd_flow" and (
                    spec.aggregation != "flow_sum" or not spec.period_start_field
                ):
                    raise WorkspaceError(
                        422, "YTD requires disjoint period flows, never cumulative/YTD snapshots"
                    )
                grouping = list(dict.fromkeys([request.account_field, *request.group_by]))
                if request.operation == "ytd_flow" and set(grouping).intersection(
                    {spec.time_field, spec.period_start_field}
                ):
                    raise WorkspaceError(
                        422, "YTD combines period intervals into one fiscal coverage"
                    )
                groups = aggregate_rows(spec, rows, schema_version, grouping, request.as_of)
                if request.operation == "ytd_flow":
                    _apply_coverage(groups, spec, rows, _period_coverage(spec, rows, request))
    except DecimalException as exc:
        raise WorkspaceError(422, "Finance calculation exceeds exact numeric precision") from exc
    state: Literal["DERIVED", "INCOMPLETE", "UNAVAILABLE", "MATCHED", "UNRECONCILED"] = (
        "DERIVED" if groups else "UNAVAILABLE"
    )
    if comparisons:
        state = (
            "MATCHED" if all(row["state"] == "MATCHED" for row in comparisons) else "UNRECONCILED"
        )
    if missing or unmapped or any(group.get("state") == "INCOMPLETE" for group in groups):
        state = "INCOMPLETE"
    return FinanceCalculation(
        operation=request.operation,
        state=state,
        starts_on=request.starts_on,
        as_of=request.as_of,
        input_count=len(rows),
        input_grain=spec.grain,
        unit_field=spec.unit_field,
        partition_fields=spec.partition_fields,
        groups=groups,
        comparisons=comparisons,
        missing_accounts=missing,
        unmapped_accounts=unmapped,
        coverage="EXPLICIT_PERIOD_INTERVALS" if spec.period_start_field else "SELECTED_FACTS_ONLY",
    )


def _collect(principal: Principal, request: FinanceExecutionRequest) -> list[dict]:
    page = query_objects(principal, request.query.model_copy(update={"limit": 200}))
    total, rows, offsets = page.total, list(page.objects), set()
    if total > 10000:
        raise WorkspaceError(422, "Finance execution supports 10000 facts; narrow the query")
    while page.next_offset is not None:
        if page.next_offset in offsets or len(rows) >= 10000:
            raise WorkspaceError(409, "Finance materialization changed or exceeded its bound")
        offsets.add(page.next_offset)
        page = query_objects(principal, page.query.model_copy(update={"offset": page.next_offset}))
        if page.total != total:
            raise WorkspaceError(409, "Finance materialization changed during collection")
        rows.extend(page.objects)
    if len(rows) != total:
        raise WorkspaceError(409, "Finance materialization is incomplete")
    return rows


def execute(principal: Principal, request: FinanceExecutionRequest, *, retain: bool = True) -> dict:
    """API/shared-function boundary: reviewed pins, authorized facts, existing retained runs."""
    require_permission(principal, "ontology_read")
    if request.query.known_at is not None and request.query.known_at > datetime.now(UTC):
        raise WorkspaceError(422, "Finance knowledge timestamp cannot be in the future")
    if request.as_of.strftime("%Y-%m") != principal.scope.period:
        raise WorkspaceError(409, "Finance as-of period differs from the invoking exact scope")
    contract = ontology_definitions.definition(
        principal, request.contract.resource_id, request.contract.version_id
    )
    if contract["object_type"] != "FactContract":
        raise WorkspaceError(422, "Finance execution requires a reviewed FactContract")
    schema_pins = [pin for pin in contract["dependencies"] if pin["relation"] == "FIELD:schema_id"]
    if len(schema_pins) != 1 or request.query.object_type != schema_pins[0]["identity_key"]:
        raise WorkspaceError(409, "Finance query differs from the exact fact schema")
    schema = schema_pins[0]
    spec = FactContract.model_validate(contract["attributes"]["definition"])
    projection_row, projection = None, None
    if request.projection:
        projection_row = ontology_definitions.definition(
            principal, request.projection.resource_id, request.projection.version_id
        )
        if projection_row["object_type"] != "FinanceProjectionDefinition":
            raise WorkspaceError(
                409, "Finance projection requires a reviewed projection definition"
            )
        projection = FinanceProjectionDefinition.model_validate(
            projection_row["attributes"]["definition"]
        )
        if projection.exact_scope != principal.scope:
            raise WorkspaceError(409, "Finance projection belongs to a different exact scope")
    rows = _collect(principal, request)
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        for row in [contract, *([projection_row] if projection_row else [])]:
            current = _current(
                cursor,
                principal,
                VersionReference(resource_id=row["resource_id"], version_id=row["version_id"]),
            )
            if current["access_entity"] != principal.scope.legal_entity_id:
                raise WorkspaceError(409, "Finance definitions must belong to the selected company")
            upstream_authority(cursor, principal.scope.tenant_id, row["version_id"])
        if projection:
            assert projection_row is not None
            indexed = {pin["relation"]: pin for pin in projection_row["dependencies"]}

            def retained_target(identity, owner, relation, version):
                pin = indexed.get(relation)
                if (
                    not pin
                    or str(pin["resource_id"]) != identity
                    or str(pin["version_id"]) != version
                ):
                    raise WorkspaceError(409, "Projection exact dependency is unavailable")
                return _current(
                    cursor, principal, VersionReference(resource_id=identity, version_id=version)
                )

            validate_projection(
                ResourceMutation(
                    object_type="FinanceProjectionDefinition",
                    resource_id=projection_row["resource_id"],
                    identity_key=projection_row["identity_key"],
                    display_name=projection_row["display_name"],
                    attributes=projection_row["attributes"],
                    valid_from=projection_row["valid_from"],
                    access_entity=projection_row["access_entity"],
                ),
                retained_target,
            )
        for row in rows:
            if row.get("access_entity") != principal.scope.legal_entity_id:
                raise WorkspaceError(
                    409, "Finance query contains facts outside the selected company"
                )
            if row.get("authority_state") != "APPROVED":
                raise WorkspaceError(409, "Finance execution requires reviewed input versions")
            if projection and str(row["attributes"].get(projection.account_field)) in {
                str(ref.resource_id) for ref in projection.expected_accounts
            }:
                account = next(
                    ref
                    for ref in projection.expected_accounts
                    if str(ref.resource_id) == str(row["attributes"][projection.account_field])
                )
                bound = cursor.execute(
                    "SELECT target_resource_id,target_version_id FROM resource_dependencies "
                    "WHERE tenant_id=%s AND version_id=%s AND relation=%s",
                    (
                        principal.scope.tenant_id,
                        row["version_id"],
                        "FIELD:" + projection.account_field,
                    ),
                ).fetchall()
                if (
                    len(bound) != 1
                    or str(bound[0]["target_resource_id"]) != str(account.resource_id)
                    or str(bound[0]["target_version_id"]) != str(account.version_id)
                ):
                    raise WorkspaceError(
                        409, "Fact account version differs from the reviewed projection"
                    )
    result = calculate(spec, rows, str(schema["version_id"]), request, projection).model_dump(
        mode="json"
    )
    result.update(
        scope=principal.scope.model_dump(mode="json"),
        request=request.model_dump(mode="json"),
        fact_contract=_pin(contract),
        schema=_pin(schema),
        projection=_pin(projection_row) if projection_row else None,
        source_versions=[_pin(row) for row in rows],
        definition_dependencies=[_pin(pin) for pin in contract["dependencies"]],
        projection_dependencies=[_pin(pin) for pin in projection_row["dependencies"]]
        if projection_row
        else [],
    )
    return (
        fact_runs.retain_run(principal, result, runtime="finance-catalog/1") if retain else result
    )


def execute_journal_trial_balance(
    principal: Principal, request: CanonicalJournalTrialBalanceRequest, *, retain: bool = True
) -> dict:
    """Resolve canonical journal bundles through their existing exact accounting reader.

    Date, ledger, currency and source identity come from retained relationships
    verified by company_journals.detail. Normalized rows are transient projections.
    """
    from finai_api.domain.object_sets import ObjectSetQuery
    from finai_api.services import company_journals

    require_permission(principal, "ontology_read")
    if request.as_of.strftime("%Y-%m") != principal.scope.period:
        raise WorkspaceError(409, "Journal turnover period differs from the invoking exact scope")
    at = company_journals.read_time(request.snapshot_at)
    expected = {
        "legal_entity_id": request.company,
        "ledger_id": request.ledger,
        "book_id": request.book,
        "period_id": request.period,
    }

    def check_selection(result):
        for name, reference in expected.items():
            actual = result["selection"].get(name)
            if actual is None or any(
                str(actual.get(field)) != str(getattr(reference, field))
                for field in ("resource_id", "version_id")
            ):
                raise WorkspaceError(409, "Canonical journal accounting selection changed")
        if result["snapshot_at"] != at.isoformat():
            raise WorkspaceError(409, "Canonical journal snapshot changed during calculation")

    arguments = (
        principal,
        request.company.resource_id,
        request.ledger.resource_id,
        request.book.resource_id,
        request.period.resource_id,
    )
    page = company_journals.list_journals(*arguments, limit=50, offset=0, snapshot_at=at)
    check_selection(page)
    if page["total"] > request.max_journals:
        raise WorkspaceError(
            422, "Canonical journal calculation exceeds its declared journal bound"
        )
    journals, offsets, total = list(page["items"]), set(), page["total"]
    while True:
        if page["coverage"]["state"] != "COMPLETE":
            raise WorkspaceError(409, "Unresolved canonical journals prevent complete turnover")
        offset = page["next_offset"]
        if offset is None:
            break
        if offset in offsets:
            raise WorkspaceError(409, "Canonical journal pagination repeated an offset")
        offsets.add(offset)
        page = company_journals.list_journals(*arguments, limit=50, offset=offset, snapshot_at=at)
        check_selection(page)
        if page["total"] != total:
            raise WorkspaceError(409, "Canonical journal collection changed during calculation")
        journals.extend(page["items"])
    if len(journals) != total:
        raise WorkspaceError(409, "Canonical journal collection is incomplete")
    rows, provenance, incomplete_dimensions = [], [], []
    seen_journals = set()
    for item in journals:
        journal_ref = VersionReference(
            resource_id=item["journal"]["resource_id"], version_id=item["journal"]["version_id"]
        )
        if journal_ref.resource_id in seen_journals:
            raise WorkspaceError(409, "Canonical journal collection repeats an entry")
        seen_journals.add(journal_ref.resource_id)
        detail = company_journals.detail(
            *arguments, journal_ref.resource_id, journal_ref.version_id, snapshot_at=at
        )
        check_selection(detail)
        if detail["integrity"]["state"] != "COMPLETE_BALANCED":
            raise WorkspaceError(
                409, "Incomplete or unbalanced canonical journal cannot enter turnover"
            )
        journal, binding = detail["journal"], detail["binding"]
        posting_date = _date(journal["attributes"].get("posting_date"))
        if not request.starts_on <= posting_date <= request.as_of:
            raise WorkspaceError(422, "Canonical journal posting falls outside requested coverage")
        for resolved in detail["lines"]:
            line, account, record = resolved["line"], resolved["account"], resolved["source_record"]
            if line["evidence_class"] != "SOURCE_BOUND":
                raise WorkspaceError(409, "Journal turnover requires source-bound canonical lines")
            if line["access_entity"] != principal.scope.legal_entity_id:
                raise WorkspaceError(409, "Journal line belongs to another company access scope")
            # The adapter schema is explicitly virtual; actual source schema pins
            # remain below. No schema or canonical accounting row is rewritten.
            rows.append(
                {
                    **line,
                    "schema_version_id": "canonical-journal-turnover-adapter/1",
                    "attributes": {
                        "line_id": line["resource_id"],
                        "account_id": account["resource_id"],
                        "posting_date": posting_date.isoformat(),
                        "side": line["attributes"]["side"],
                        "amount": line["attributes"]["amount"]["amount"],
                        "currency_id": line["attributes"]["amount"]["currency_id"],
                        "ledger_id": str(request.ledger.resource_id),
                        "book_id": str(request.book.resource_id),
                        "source_family": "EXACT_CANONICAL_JOURNAL_BUNDLE",
                    },
                }
            )
            provenance.append(
                {
                    "line": _pin(line),
                    "journal": _pin(journal),
                    "account": _pin(account),
                    "source_record": _pin(record),
                    "accounting_binding": _pin(binding),
                    "schema_version_id": str(line["schema_version_id"]),
                    "dimensions": resolved["dimensions"],
                }
            )
            if resolved["dimensions"]["state"] != "COMPLETE":
                incomplete_dimensions.append(_pin(line))
            if len(rows) > 10000:
                raise WorkspaceError(422, "Canonical journal turnover exceeds the 10000 line bound")
    contract = FactContract(
        grain=[
            "line_id",
            "account_id",
            "posting_date",
            "currency_id",
            "ledger_id",
            "book_id",
            "side",
        ],
        dimensions=["account_id", "posting_date", "ledger_id", "book_id", "side"],
        measure="amount",
        aggregation="flow_sum",
        time_field="posting_date",
        unit_field="currency_id",
        source_family="EXACT_CANONICAL_JOURNAL_BUNDLE",
        source_family_field="source_family",
        partition_fields=["ledger_id", "book_id"],
        authority_basis="Exact retained balanced canonical journal and source accounting bindings",
    )
    internal_request = FinanceExecutionRequest(
        operation="trial_balance",
        contract=request.period,
        query=ObjectSetQuery(object_type="JournalLine", valid_at=at, known_at=at),
        starts_on=request.starts_on,
        as_of=request.as_of,
        side_field="side",
    )
    result = calculate(
        contract, rows, "canonical-journal-turnover-adapter/1", internal_request
    ).model_dump(mode="json")
    result.update(
        implementation_id="finance.canonical-journal-turnover/1",
        scope=principal.scope.model_dump(mode="json"),
        request=request.model_dump(mode="json"),
        selection=page["selection"],
        journal_count=len(journals),
        source_versions=provenance,
        normalized_fact_contract=contract.model_dump(mode="json"),
        dimension_coverage={
            "state": "INCOMPLETE" if incomplete_dimensions else "COMPLETE",
            "incomplete_lines": incomplete_dimensions,
            "effect": "Account turnover only; analytical allocations are not inferred",
        },
    )
    return (
        fact_runs.retain_run(principal, result, runtime="finance-catalog/1") if retain else result
    )

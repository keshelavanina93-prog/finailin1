"""Generic source-linked ACCOUNT_PERIOD trial-balance draft producer.

This module consumes retained BIFF sources through the normal exact-scope
evidence store.  It emits a reviewable draft graph and never promotes rows to
canonical accounting, currency, journal, or petroleum operating facts.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.review import Principal
from finai_api.services import fact_runs
from finai_api.services.finance_chartpack import (
    classification_manifest,
    classify_account,
    load_chartpack,
)
from finai_api.services.independent_tb_reader import (
    MEASURES,
    TBMonth,
    TBRow,
    mark_overlaps,
    read_tb,
)
from finai_api.services.tb_continuity import continuity_report
from finai_api.services.tb_finance_contract import (
    CONTRACT_ID,
    PROFILE,
    TbFinanceContractRequest,
    validate,
)
from finai_api.services.tb_source_family import bind_source_family, family_reuse_report
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection, retained_source

TB_DRAFT_FUNCTION = "tb_statement_draft@v1"
MAX_RECEIPTS = 24


def _decimal(value: Decimal | None) -> str:
    return format(value or Decimal(0), "f")


def _zero(value: Decimal | None) -> Decimal:
    return value or Decimal(0)


def _net(row: TBRow, prefix: str) -> Decimal:
    return _zero(row.amounts[f"{prefix}_debit"]) - _zero(row.amounts[f"{prefix}_credit"])


def _flow(row: TBRow, measure: str | None) -> Decimal:
    return _zero(row.amounts[measure]) if measure else Decimal(0)


def _source_row(row: TBRow, *, receipt_id: str, source_sha256: str) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "source_sha256": source_sha256,
        "source_row": row.source_row,
        "coordinates": dict(row.coordinates),
        "account_code": row.account_code,
        "account_name": row.account_name,
        "subkonto": row.subkonto,
        "outline_role": row.outline_role,
        "outline_level": row.outline_level,
        "parent_row": row.parent_row,
        "parent_code": row.parent_code,
    }


def _receipt_rows(principal: Principal, receipt_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not receipt_ids:
        raise WorkspaceError(422, "Select retained TB receipts before producing a draft")
    if len(receipt_ids) > MAX_RECEIPTS:
        raise WorkspaceError(422, f"A TB draft accepts at most {MAX_RECEIPTS} retained receipts")
    if len(set(receipt_ids)) != len(receipt_ids):
        raise WorkspaceError(422, "A TB draft cannot repeat a retained receipt")
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT receipt_id, request, receipt, exact_scope, source_storage, source_sha256 "
            "FROM hydration_runs WHERE tenant_id=%s AND exact_scope=%s "
            "AND receipt_id=ANY(%s::text[])",
            (principal.scope.tenant_id, Jsonb(scope), list(receipt_ids)),
        ).fetchall()
    found = {str(row["receipt_id"]): row for row in rows}
    missing = sorted(set(receipt_ids) - set(found))
    if missing:
        raise WorkspaceError(404, "Retained TB receipt is unavailable in the exact scope")
    return [found[receipt_id] for receipt_id in receipt_ids]


def _load_months(
    principal: Principal, receipt_ids: Sequence[str]
) -> tuple[tuple[TBMonth, ...], tuple[str, ...], tuple[dict[str, Any], ...]]:
    rows = _receipt_rows(principal, receipt_ids)
    months: list[TBMonth] = []
    ordered_receipts: list[str] = []
    metadata: list[dict[str, Any]] = []
    seen_periods: set[str] = set()
    for row in rows:
        receipt = row["receipt"]
        if receipt.get("source_class") != "TRIAL_BALANCE":
            raise WorkspaceError(422, "TB Finance accepts only retained trial-balance receipts")
        try:
            content = retained_source(principal.scope, row)
            month = read_tb(
                content, filename=str(row["request"].get("filename", row["receipt_id"]))
            )
        except WorkspaceError:
            raise
        except Exception as exc:
            raise WorkspaceError(
                422, "A retained receipt is not a compatible 1C TB source"
            ) from exc
        if month.period in seen_periods:
            raise WorkspaceError(409, f"Observed period {month.period} is selected more than once")
        seen_periods.add(month.period)
        months.append(month)
        ordered_receipts.append(str(row["receipt_id"]))
        metadata.append(
            {
                "receipt_id": str(row["receipt_id"]),
                "source_sha256": str(row["source_sha256"]),
                "submitted_by": row.get("submitted_by"),
                "source_use": row["request"].get("source_use", "ACTUAL_INPUT"),
                "credential_period": row["request"].get("scope", {}).get("period"),
                "observed_period": month.period,
                "period_authority": "SOURCE_INTERNAL_HEADER",
                "period_coordinate": f"{month.sheet}!C3",
                "ingestion_timestamp": row.get("ingested_at"),
                "prior_rejects": list(receipt.get("rejects", [])),
            }
        )
    paired = sorted(
        zip(months, ordered_receipts, metadata, strict=True),
        key=lambda item: item[0].period,
    )
    return (
        tuple(item[0] for item in paired),
        tuple(item[1] for item in paired),
        tuple(item[2] for item in paired),
    )


def list_retained_tb_sources(principal: Principal) -> list[dict[str, Any]]:
    """List retained TB snapshots without selecting a source on the caller's behalf."""

    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT receipt_id, request, receipt, source_sha256, submitted_by, ingested_at "
            "FROM hydration_runs WHERE tenant_id=%s AND exact_scope=%s "
            "AND receipt->>'source_class'='TRIAL_BALANCE' ORDER BY ingested_at, receipt_id "
            "LIMIT 100",
            (principal.scope.tenant_id, Jsonb(scope)),
        ).fetchall()
    result = []
    for row in rows:
        receipt = row["receipt"]
        result.append(
            {
                "receipt_id": str(row["receipt_id"]),
                "filename": row["request"].get("filename"),
                "source_sha256": str(row["source_sha256"]),
                "observed_period": receipt.get("observed_bindings", {}).get("period"),
                "working_period": row["request"].get("scope", {}).get("period"),
                "period_authority": "SOURCE_INTERNAL_HEADER",
                "period_coordinate": receipt.get("observed_bindings", {}).get(
                    "period_coordinate", "TDSheet!C3"
                ),
                "source_use": row["request"].get("source_use", "ACTUAL_INPUT"),
                "rejects": list(receipt.get("rejects", [])),
                "warnings": list(receipt.get("warnings", [])),
                "submitted_by": row.get("submitted_by"),
                "ingested_at": row.get("ingested_at"),
            }
        )
    return result


def _classify_root(row: TBRow, pack) -> Any:
    account_code = row.account_code or (row.account_path[0] if row.account_path else None)
    return classify_account(
        account_code,
        subkonto=row.subkonto,
        additive_ok=row.additive_ok,
        duplicate_of=row.duplicate_of,
        pack=pack,
    )


def _sum_class(rows: Iterable[tuple[TBRow, Any]], local_class: str, measure: str) -> Decimal:
    return sum(
        (
            _flow(row, measure)
            for row, classification in rows
            if classification.local_account_class == local_class and classification.additive_ok
        ),
        Decimal(0),
    )


def _balance_class(rows: Iterable[tuple[TBRow, Any]], local_class: str) -> Decimal:
    return sum(
        (
            _net(row, "closing")
            for row, classification in rows
            if classification.local_account_class == local_class and classification.additive_ok
        ),
        Decimal(0),
    )


def _analytic_rows(month: TBMonth) -> list[TBRow]:
    return [
        row
        for row in month.rows
        if row.subkonto and row.account_path and row.account_path[0].startswith("141")
    ]


def _pulse(month: TBMonth, pack, boundary_status: str) -> dict[str, Any]:
    roots = tuple((row, _classify_root(row, pack)) for row in month.root_rows)
    revenue = _sum_class(roots, "revenue", "turnover_credit")
    cogs = _sum_class(roots, "cost_of_goods_sold", "turnover_debit")
    selling = _sum_class(roots, "selling_expense", "turnover_debit")
    admin = _sum_class(roots, "administrative_expense", "turnover_debit")
    other_income = _sum_class(roots, "other_income", "turnover_credit")
    other_expense = _sum_class(roots, "other_expense", "turnover_debit")
    shortage = _sum_class(roots, "shortage", "turnover_debit")
    return {
        "period": month.period,
        "revenue_month": _decimal(revenue),
        "cogs_month": _decimal(cogs),
        "gross_margin_month": _decimal(revenue - cogs),
        "selling_exp_month": _decimal(selling),
        "admin_exp_month": _decimal(admin),
        "other_income_month": _decimal(other_income),
        "other_exp_month": _decimal(other_expense),
        "shortage_month": _decimal(shortage),
        "cash_end": _decimal(
            _balance_class(roots, "cash_and_equivalents") + _balance_class(roots, "cash_in_transit")
        ),
        "inventory_end": _decimal(
            _balance_class(roots, "goods_in_transit")
            + _balance_class(roots, "merchandise_inventory")
        ),
        "ar_end": _decimal(_balance_class(roots, "trade_receivables")),
        "ap_end": _decimal(_balance_class(roots, "trade_payables")),
        "st_debt_end": _decimal(_balance_class(roots, "short_term_debt")),
        "continuity_status": boundary_status,
        "unit": "source_amount",
    }


FACT_COLUMNS = (
    "fact_id",
    "grain",
    "period",
    "account_code",
    "analytic",
    "measures",
    "signed_open",
    "signed_close",
    "additive_ok",
    "classification",
    "source_index",
    "source_row",
)


def _compact_fact(
    fact_id: str,
    grain: str,
    month: TBMonth,
    row: TBRow,
    classification: Mapping[str, Any],
    source_index: int,
) -> list[Any]:
    # The source snapshot table carries the immutable receipt/hash/sheet.  A
    # fact therefore needs only an integer source reference and row number;
    # the fixed 1C measure columns are part of this function's contract.  The
    # compact shape keeps a twelve-month evidence package below the retained
    # calculation-run bound without dropping drillability.
    measures = {
        key: _decimal(row.amounts[key]) for key in MEASURES if _zero(row.amounts[key]) != Decimal(0)
    }
    selected = {
        key: classification.get(key)
        for key in (
            "state",
            "rule_key",
            "analytic_dimension",
        )
    }
    return [
        fact_id,
        grain,
        month.period,
        row.account_code,
        row.subkonto,
        measures,
        _decimal(_net(row, "opening")),
        _decimal(_net(row, "closing")),
        row.additive_ok,
        selected,
        source_index,
        row.source_row,
    ]


def _account_period_facts(
    months: Sequence[TBMonth], receipt_ids: Sequence[str], pack
) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    # Root facts remain verbose because they are the statement aggregation
    # frontier.  Detail/subkonto facts use FACT_COLUMNS plus a source index;
    # both shapes retain ACCOUNT_PERIOD grain and source-row drill.
    root_facts: list[dict[str, Any]] = []
    analytic_facts: list[list[Any]] = []
    for source_index, (month, receipt_id) in enumerate(zip(months, receipt_ids, strict=True)):
        for row in month.root_rows:
            classification = _classify_root(row, pack).model_dump(mode="json")
            root_facts.append(
                {
                    "fact_id": "apf_"
                    + sha256(f"{month.source_sha256}:{row.source_row}".encode()).hexdigest(),
                    "grain": "ACCOUNT_PERIOD",
                    "period": month.period,
                    "account_code": row.account_code,
                    "analytic": None,
                    "measures": {key: _decimal(row.amounts[key]) for key in MEASURES},
                    "signed_open": _decimal(_net(row, "opening")),
                    "signed_close": _decimal(_net(row, "closing")),
                    "additive_ok": row.additive_ok,
                    "authority_state": "MAPPED_CANDIDATE",
                    "evidence_class": "SOURCE_BOUND",
                    "classification": classification,
                    "lineage": _source_row(
                        row, receipt_id=receipt_id, source_sha256=month.source_sha256
                    ),
                }
            )
        for row in _analytic_rows(month):
            classification = _classify_root(row, pack).model_dump(mode="json")
            analytic_facts.append(
                _compact_fact(
                    "apf_"
                    + sha256(
                        f"{month.source_sha256}:{row.source_row}:analytic".encode()
                    ).hexdigest(),
                    "ACCOUNT_PERIOD_ANALYTIC",
                    month,
                    row,
                    classification,
                    source_index,
                )
            )
    return root_facts, analytic_facts


def _draft_sections(months: Sequence[TBMonth], pack, continuity: dict[str, Any]) -> dict[str, Any]:
    pulses = []
    continuity_by_period = defaultdict(list)
    for item in continuity["breaks"]:
        continuity_by_period[item["period_to"]].append(item)
    for month in months:
        status = (
            "BREAKS_OPEN"
            if continuity_by_period[month.period]
            else (
                "FIRST_RETAINED_PERIOD" if month.period == months[0].period else "CONTINUITY_PASS"
            )
        )
        pulses.append(_pulse(month, pack, status))

    pnl_classes = {
        "revenue": "revenue",
        "cogs": "cost_of_goods_sold",
        "selling": "selling_expense",
        "admin": "administrative_expense",
        "other_income": "other_income",
        "other_exp": "other_expense",
        "shortage": "shortage",
    }
    turnover_keys = {
        "revenue": "revenue_month",
        "cogs": "cogs_month",
        "selling": "selling_exp_month",
        "admin": "admin_exp_month",
        "other_income": "other_income_month",
        "other_exp": "other_exp_month",
        "shortage": "shortage_month",
    }
    pnl_monthly = []
    natural_closing = []
    for month, pulse in zip(months, pulses, strict=True):
        roots = tuple((row, _classify_root(row, pack)) for row in month.root_rows)
        pnl_monthly.append(
            {
                "period": pulse["period"],
                "revenue_month": pulse["revenue_month"],
                "cogs_month": pulse["cogs_month"],
                "gross_margin_month": pulse["gross_margin_month"],
                "selling_exp_month": pulse["selling_exp_month"],
                "admin_exp_month": pulse["admin_exp_month"],
                "other_income_month": pulse["other_income_month"],
                "other_exp_month": pulse["other_exp_month"],
                "shortage_month": pulse["shortage_month"],
            }
        )
        natural_closing.append(
            {
                key: _decimal(_balance_class(roots, local_class))
                for key, local_class in pnl_classes.items()
            }
        )
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    ytd = []
    for item, natural in zip(pnl_monthly, natural_closing, strict=True):
        for key, value in item.items():
            if key != "period":
                totals[key] += Decimal(value)
        turnover_ytd = {key: _decimal(value) for key, value in totals.items()}
        natural_values = {key: natural[key] for key in pnl_classes}
        disagreement = [
            key
            for key in pnl_classes
            if Decimal(turnover_ytd[turnover_keys[key]]) != Decimal(natural_values[key])
        ]
        ytd.append(
            {
                "period": item["period"],
                **turnover_ytd,
                "turnover_ytd": turnover_ytd,
                "natural_closing": natural_values,
                "finding": ("NATURAL_CLOSING_DIFFERS_FROM_TURNOVER_YTD" if disagreement else None),
                "disagreement_lines": disagreement,
            }
        )

    bs = [
        {
            "period": pulse["period"],
            "cash_end": pulse["cash_end"],
            "inventory_end": pulse["inventory_end"],
            "ar_end": pulse["ar_end"],
            "ap_end": pulse["ap_end"],
            "st_debt_end": pulse["st_debt_end"],
            "snapshot_policy": "MONTH_END_SNAPSHOT_NOT_SUMMED",
        }
        for pulse in pulses
    ]
    cash = [
        {
            "period": pulse["period"],
            "cash_end": pulse["cash_end"],
            "monthly_net_change": _decimal(
                Decimal(pulse["cash_end"])
                - (Decimal(pulses[index - 1]["cash_end"]) if index else Decimal(0))
            ),
            "label": "CASH_BRIDGE_FROM_TB",
            "certification": "NOT_CERTIFIED",
        }
        for index, (pulse, previous) in enumerate(zip(pulses, [None, *pulses[:-1]], strict=True))
    ]
    inventory = []
    ar = []
    ap_debt = []
    for month, pulse in zip(months, pulses, strict=True):
        roots = tuple((row, _classify_root(row, pack)) for row in month.root_rows)
        inventory_classes = {"goods_in_transit", "merchandise_inventory"}
        goods_open = sum(
            (
                _net(row, "opening")
                for row, c in roots
                if c.local_account_class in inventory_classes and c.additive_ok
            ),
            Decimal(0),
        )
        goods_in = sum(
            (
                _flow(row, "turnover_debit")
                for row, c in roots
                if c.local_account_class in inventory_classes and c.additive_ok
            ),
            Decimal(0),
        )
        goods_out = sum(
            (
                _flow(row, "turnover_credit")
                for row, c in roots
                if c.local_account_class in inventory_classes and c.additive_ok
            ),
            Decimal(0),
        )
        cogs = Decimal(pulse["cogs_month"])
        inventory.append(
            {
                "period": month.period,
                "open": _decimal(goods_open),
                "in_debit_turnover": _decimal(goods_in),
                "out_credit_turnover": _decimal(goods_out),
                "close": pulse["inventory_end"],
                "cogs_month": _decimal(cogs),
                "out_vs_cogs_residual": _decimal(goods_out - cogs),
                "finding": "REVIEW_REQUIRED" if goods_out != cogs else None,
            }
        )
        analytic_labels: dict[str, set[str]] = {
            "site_analytic": set(),
            "counterparty_analytic": set(),
        }
        for row in _analytic_rows(month):
            classification = _classify_root(row, pack)
            dimension = classification.analytic_dimension or "counterparty_analytic"
            if row.subkonto:
                analytic_labels.setdefault(dimension, set()).add(row.subkonto)
        analytics = {key: len(values) for key, values in analytic_labels.items()}
        ar.append(
            {
                "period": month.period,
                "trade_receivables_end": pulse["ar_end"],
                "analytics": analytics,
                "title": "Receivables by analytic",
            }
        )
        ap_debt.append(
            {
                "period": month.period,
                "trade_payables_end": pulse["ap_end"],
                "short_term_debt_end": pulse["st_debt_end"],
                "title": "Payables and debt",
            }
        )
    return {
        "year_pulse": pulses,
        "pnl_draft": {
            "monthly": pnl_monthly,
            "ytd": ytd,
            "ytd_policy": (
                "SHOW_MONTHLY_TURNOVER_SUM_AND_NATURAL_SOURCE_CLOSING; FLAG_DISAGREEMENT"
            ),
        },
        "bs_draft": bs,
        "cash_draft": cash,
        "inventory_value_draft": inventory,
        "receivables_by_analytic": ar,
        "payables_debt": ap_debt,
    }


def build_draft(
    principal: Principal,
    receipt_ids: Sequence[str],
    *,
    working_period: str | None = None,
    chartpack_id: str = "chartpack.1c_ge_statutory.v1",
    persist: bool = True,
) -> dict[str, Any]:
    """Produce and optionally retain a deterministic source-linked TB draft."""

    contract = validate(
        TbFinanceContractRequest(
            profile=PROFILE,
            requested_objects=("SourceFamily", "SourcePeriodSnapshot", "AccountPeriodFact"),
            requested_outputs=("StatementDraft", "ContinuityFinding", "NOT_CERTIFIED_EXPORT"),
            currency_status="UNREVIEWED",
        )
    ).model_dump(mode="json")
    if chartpack_id != "chartpack.1c_ge_statutory.v1":
        raise WorkspaceError(404, f"ChartPack {chartpack_id!r} is not installed")
    months, ordered_receipts, metadata = _load_months(principal, receipt_ids)
    pack = load_chartpack(chartpack_id)
    marked = tuple(mark_overlaps(month) for month in months)
    family = bind_source_family(
        marked,
        receipt_ids=ordered_receipts,
        working_period=working_period or principal.scope.period,
    )
    effective_working_period = working_period or principal.scope.period
    period_findings = [
        {
            "code": "OBSERVED_PERIOD_WORKING_SCOPE_MISMATCH",
            "receipt_id": metadata[index]["receipt_id"],
            "source_sha256": month.source_sha256,
            "observed_period": month.period,
            "working_period": effective_working_period,
            "coordinate": f"{month.sheet}!C3",
            "severity": "REVIEW_REQUIRED",
            "message": (
                f"Source heading establishes {month.period}; working scope is "
                f"{effective_working_period}. The source heading remains authoritative; "
                "no period coercion or current-date fallback was applied."
            ),
        }
        for index, month in enumerate(marked)
        if month.period != effective_working_period
    ]
    continuity = continuity_report(marked)
    sections = _draft_sections(marked, pack, continuity)
    hashes = [month.source_sha256 for month in marked]
    roots = [row for month in marked for row in month.root_rows]
    classifications = classification_manifest(
        roots,
        source_family=family.family_id,
        source_hashes=hashes,
        pack=pack,
    )
    root_facts, analytic_facts = _account_period_facts(marked, ordered_receipts, pack)
    unmapped = sorted(
        {
            row.account_code
            for row in roots
            if row.account_code
            and classify_account(row.account_code, pack=pack).state == "UNMAPPED"
        }
    )
    overlap_rows = [
        _source_row(
            row,
            receipt_id=ordered_receipts[index],
            source_sha256=marked[index].source_sha256,
        )
        for index, month in enumerate(marked)
        for row in month.rows
        if not row.additive_ok and row.duplicate_of is not None
    ]
    result: dict[str, Any] = {
        "function": TB_DRAFT_FUNCTION,
        "contract_id": CONTRACT_ID,
        "profile": PROFILE,
        "contract": contract,
        "scope": principal.scope.model_dump(mode="json"),
        "source_class": "1C_TURNOVER_TRIAL_BALANCE",
        "source_family": family.as_dict(),
        "source_snapshots": list(family.as_dict()["snapshots"]),
        "period_authority": {
            "accounting_period": "SOURCE_INTERNAL_HEADER",
            "period_coordinate": "TDSheet!C3",
            "working_period": effective_working_period,
            "ingestion_timestamp_field": "hydration_runs.ingested_at",
            "current_date_used_for_accounting_period": False,
            "mismatch_behavior": "EXPLICIT_REVIEW_FINDING_NO_COERCION",
        },
        "source_receipts": list(metadata),
        "chartpack": {
            "pack_id": pack.pack_id,
            "version": pack.version,
            "mapping_status": pack.mapping_status,
            "authority": pack.authority,
        },
        "classification_proposal": classifications,
        "fact_columns": list(FACT_COLUMNS),
        "account_period_facts": root_facts,
        "account_period_analytic_facts": analytic_facts,
        "continuity": continuity,
        "family_reuse": family_reuse_report(marked),
        **sections,
        "exceptions": {
            "period_findings": period_findings,
            "continuity_breaks": continuity["breaks"],
            "unmapped_root_codes": unmapped,
            "hierarchy_overlap_count": len(overlap_rows),
            "hierarchy_overlaps": overlap_rows[:100],
            "cash_in_transit_negative": False,
            "unsupported": [
                "canonical_journals",
                "invoices",
                "due_dates",
                "aging",
                "liters",
                "tanks",
                "trucks",
                "product_margin",
                "live_map",
                "GEL_currency_inference",
            ],
        },
        "lineage": {
            "source_hashes": hashes,
            "receipt_ids": list(ordered_receipts),
            "deepest_drill": "retained_source_hash + source_row + source_columns",
        },
        "review": {
            "classification_state": "CLASSIFICATION_UNREVIEWED",
            "snapshot_state": "DRAFT_INPUT",
            "year_package_state": "DRAFT_ONLY",
            "accounting_use_authorized": False,
            "business_effect_authorized": False,
            "currency_status": "UNREVIEWED",
            "certification": "NOT_CERTIFIED",
            "petroleum_actuals": "UNIMPLEMENTED",
        },
        "unit": "source_amount",
        "certification": "NOT_CERTIFIED",
    }
    if persist:
        result = fact_runs.retain_run(principal, result, runtime="tb-finance-draft/1")
    return result


def export_zip(draft: Mapping[str, Any]) -> bytes:
    """Create a two-file NOT_CERTIFIED draft bundle."""

    workbook = Workbook()
    pulse = workbook.active
    pulse.title = "Year Pulse"
    rows = draft.get("year_pulse", [])
    headers = list(rows[0].keys()) if rows else ["period"]
    pulse.append(headers)
    for row in rows:
        pulse.append([row.get(header) for header in headers])
    for title, key in (
        ("P&L Draft", "pnl_draft"),
        ("BS Draft", "bs_draft"),
        ("Continuity", "continuity"),
    ):
        sheet = workbook.create_sheet(title)
        value = draft.get(key, {})
        sheet.append(["certification", "NOT_CERTIFIED"])
        sheet.append(["payload_json", json.dumps(value, ensure_ascii=False, sort_keys=True)])
    output = BytesIO()
    workbook.save(output)
    workbook_bytes = output.getvalue()
    sidecar = json.dumps(
        {
            "contract": CONTRACT_ID,
            "function": TB_DRAFT_FUNCTION,
            "certification": "NOT_CERTIFIED",
            "source_hashes": draft.get("lineage", {}).get("source_hashes", []),
            "chartpack": draft.get("chartpack"),
            "breaks": draft.get("continuity", {}).get("breaks", []),
            "draft_hash": sha256(
                json.dumps(draft, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")
    import zipfile

    bundle = BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("TB_Finance_Draft.xlsx", workbook_bytes)
        archive.writestr("TB_Finance_Draft.json", sidecar)
    return bundle.getvalue()

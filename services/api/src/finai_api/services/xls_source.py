"""Read a bounded 1C balance export as evidence, without inventing accounting facts."""

import re
from collections import Counter
from hashlib import sha256
from typing import Any

import xlrd

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ingest import Candidate, IngestReceipt, IngestRequest

SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
MONTHS = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
FIELDS = {
    "opening_debit": 6,
    "opening_credit": 7,
    "turnover_debit": 10,
    "turnover_credit": 13,
    "closing_debit": 14,
    "closing_credit": 16,
}


def cell_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def inspect_xls(content: bytes) -> dict[str, Any]:
    if len(content) > 4_000_000 or not content.startswith(SIGNATURE):
        raise ValueError("Unsupported XLS source")
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True, formatting_info=True)
    except Exception as exc:
        raise ValueError("The XLS workbook could not be read") from exc
    try:
        if book.nsheets != 1:
            raise ValueError("This adapter requires a single-sheet 1C trial balance")
        sheet = book.sheet_by_index(0)
        if not 8 <= sheet.nrows <= 10000 or not 17 <= sheet.ncols <= 32:
            raise ValueError("Unrecognized 1C trial balance layout")
        if any(
            sheet.cell_value(r, c) != "" for r in range(sheet.nrows) for c in range(17, sheet.ncols)
        ):
            raise ValueError("Additional populated XLS columns require adapter review")
        expected = {
            (1, 2): "Оборотно-сальдовая ведомость",
            (6, 2): "Код",
            (6, 3): "Наименование",
            (5, 6): "Сальдо на начало периода",
            (5, 10): "Оборот за период",
            (5, 14): "Сальдо на конец периода",
        }
        expected.update(
            {(6, c): "Дебет" if key.endswith("debit") else "Кредит" for key, c in FIELDS.items()}
        )
        if any(sheet.cell_value(r, c) != value for (r, c), value in expected.items()):
            raise ValueError("Trial balance headers changed; an adapter review is required")
        match = re.fullmatch(r"Период: (\w+) (\d{4}) \u0433\.", cell_text(sheet.cell_value(2, 2)))
        if match is None or match[1] not in MONTHS:
            raise ValueError("The source does not establish a recognized monthly period")
        period = f"{match[2]}-{MONTHS.index(match[1]) + 1:02}"
        rows: list[dict[str, Any]] = []
        parent = ""
        stack: list[tuple[int, int, str]] = []
        for r in range(7, sheet.nrows):
            raw = sheet.row_values(r)[:17]
            if not any(value != "" for value in raw):
                continue
            code = cell_text(raw[2])
            level = sheet.rowinfo_map[r].outline_level if r in sheet.rowinfo_map else 0
            while stack and stack[-1][0] >= level:
                stack.pop()
            hierarchy_parent = str(stack[-1][1]) if stack else ""
            analytic_path = [entry[2] for entry in stack if entry[2]]
            if code:
                parent = code
            role = (
                ("ACCOUNT_GROUP" if "X" in code.upper() else "ACCOUNT_SUMMARY")
                if code
                else ("ANALYTICAL_ROW" if raw[4] != "" else "UNRESOLVED_ROW")
            )
            values = {
                "source_sheet": sheet.name,
                "source_row_role": role,
                "source_account_code": code,
                "source_account_type": str(sheet.cell_type(r, 2)),
                "parent_account_candidate": parent,
                "source_account_name": cell_text(raw[3]),
                "source_analytic_label": cell_text(raw[4]),
                "observed_period": period,
                "aggregation_policy": "NON_ADDITIVE_REVIEW_REQUIRED",
                "source_outline_level": str(level),
                "hierarchy_parent_row": hierarchy_parent,
                "hierarchy_basis": "SOURCE_OUTLINE",
                "analytic_path_candidate": " / ".join(
                    analytic_path + ([cell_text(raw[4])] if raw[4] else [])
                ),
            }
            stack.append((level, r + 1, cell_text(raw[4])))
            values.update({key: cell_text(raw[c]) for key, c in FIELDS.items()})
            # Every original cell is retained, including otherwise unclassified labels/footers.
            values.update(
                {f"cell_{chr(65 + c)}": cell_text(v) for c, v in enumerate(raw) if v != ""}
            )
            rows.append(
                {"source_row": r + 1, "values": values, "cells": [cell_text(v) for v in raw]}
            )
        codes = Counter(
            row["values"]["source_account_code"]
            for row in rows
            if row["values"]["source_account_code"]
        )
        return {
            "sheet": sheet.name,
            "period": period,
            "company_label": cell_text(sheet.cell_value(0, 2)),
            "rows": rows,
            "duplicate_codes": sorted(code for code, count in codes.items() if count > 1),
        }
    finally:
        book.release_resources()


def compile_xls(request: IngestRequest) -> IngestReceipt:
    from finai_api.services.ingestion import SourceAuthorityDenied

    if set(request.requested_objects) - {"SourceRecord"}:
        raise SourceAuthorityDenied(
            "XLS trial balance observations cannot create financial postings"
        )
    if (
        request.context_version_id
        or request.account_version_ids
        or request.account_alias_version_ids
    ):
        raise SourceAuthorityDenied(
            "Review the XLS row hierarchy before canonical financial binding"
        )
    content = request.source_bytes()
    source = inspect_xls(content)
    from finai_api.services.tb_frontier import analyze
    frontier = analyze(source["rows"])
    rejects = (
        ()
        if source["period"] == request.scope.period or request.source_use != "ACTUAL_INPUT"
        else (
            f"Source period {source['period']} differs from selected period {request.scope.period}",
        )
    )
    request_hash = canonical_sha256(request)
    return IngestReceipt(
        receipt_id=f"ir_{request_hash}",
        request_sha256=request_hash,
        source_sha256=sha256(content).hexdigest(),
        scope=request.scope,
        source_class="TRIAL_BALANCE",
        source_profile={
            "aggregation_proof": frontier,
            "version": "1c-outline-profile/1",
            "source_use": request.source_use,
            "observed_period": source["period"],
            "observed_company_label": source["company_label"],
            "findings": [
                {
                    "code": "SOURCE_TOTAL_FRONTIER",
                    "sheet": source["sheet"],
                    "message": (
                        f"{frontier['state']}: {len(frontier['selected_rows'])} root summaries. "
                        "Only these rows are used for the source-total proof. "
                        "Account/detail rows remain non-additive; account reporting depth "
                        "requires a separate approved mapping and netting policy."
                    ),
                    "coordinates": [str(r) for r in frontier["selected_rows"]],
                    "severity": "REVIEW_REQUIRED",
                },
                {
                    "code": "REPEATED_ACCOUNT_SUMMARIES",
                    "sheet": source["sheet"],
                    "message": (
                        "Repeated codes and parent/detail rows are non-additive; "
                        "choose a reviewed aggregation frontier."
                    ),
                    "coordinates": source["duplicate_codes"],
                    "occurrences": len(source["duplicate_codes"]),
                    "severity": "REVIEW_REQUIRED",
                },
                {
                    "code": "NESTED_ANALYTIC_HIERARCHY",
                    "sheet": source["sheet"],
                    "message": (
                        "Source outline levels and parent row coordinates are retained. "
                        "Subconto identities and completeness still require binding."
                    ),
                    "coordinates": [],
                    "severity": "REVIEW_REQUIRED",
                },
            ],
            "financial_promotion": "UNAVAILABLE",
        },
        classifier_version="1c-biff-tb-layout/1",
        authority_contract_version="1c-tb-observations/1",
        pack_version="finance-source/1",
        plan=(
            "preserve",
            "classify",
            "observe-context",
            "profile-hierarchy",
            "source-observations",
        ),
        observed_bindings={
            "company_label": source["company_label"],
            "period": source["period"],
            "company_coordinate": f"{source['sheet']}!C1",
            "period_coordinate": f"{source['sheet']}!C3",
        },
        used_fields=tuple(FIELDS),
        unused_fields=(),
        candidates=tuple(
            Candidate(
                object_type="SourceRecord",
                source_row=row["source_row"],
                epistemic_state="OBSERVED",
                values=row["values"],
            )
            for row in source["rows"]
        ),
        rejects=rejects,
        warnings=(
            "Source observations only; company, currency and account hierarchy need review.",
            "Cached XLS cell values are not recalculated or certified.",
            "Account summaries and analytical rows are non-additive; no journal created.",
            "Repeated source codes: " + ", ".join(source["duplicate_codes"]),
        ),
        reconciliation={"status": "REVIEW_REQUIRED", "aggregation": "NOT_PERFORMED"},
        functions_executed=("source.1c-biff-tb-inspection/1",),
    )


def preview_xls(content: bytes, offset: int = 0, search: str = "") -> dict[str, Any]:
    source = inspect_xls(content)
    rows = source["rows"]
    matching = [
        row
        for row in rows
        if not search or any(search.casefold() in value.casefold() for value in row["cells"])
    ]
    return {
        "columns": [chr(65 + i) for i in range(17)],
        "rows": [
            {"source_row": row["source_row"], "values": row["cells"], "width_matches_header": True}
            for row in matching[offset : offset + 100]
        ],
        "total_rows": len(rows),
        "matching_rows": len(matching),
        "offset": offset,
        "page_size": 100,
        "has_more": len(matching) > offset + 100,
        "sha256": sha256(content).hexdigest(),
        "byte_length": len(content),
        "integrity": "VERIFIED",
        "value_semantics": "SOURCE_CACHED_XLS_CELLS",
        "profile": [],
        "extra_width_rows": 0,
        "profile_scope": "ENTIRE_SOURCE",
        "observed_period": source["period"],
        "observed_company": source["company_label"],
    }

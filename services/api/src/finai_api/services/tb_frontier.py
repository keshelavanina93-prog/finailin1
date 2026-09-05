"""Source-only aggregation proof. A candidate frontier never grants accounting authority."""

from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

MEASURES = (
    "opening_debit",
    "opening_credit",
    "turnover_debit",
    "turnover_credit",
    "closing_debit",
    "closing_credit",
)


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    with localcontext() as ctx:
        ctx.prec = 50
        return _analyze(rows)


def _analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    amounts: dict[int, dict[str, Decimal]] = {}
    errors: list[dict[str, Any]] = []
    by_row = {r["source_row"]: r["values"] for r in rows}
    children: dict[int, list[int]] = {}
    for row, values in by_row.items():
        try:
            amount = {m: Decimal(values.get(m) or "0") for m in MEASURES}
            if any(not v.is_finite() or abs(v) >= Decimal("1e24") for v in amount.values()):
                raise ValueError("unsupported amount")
            amounts[row] = amount
        except (InvalidOperation, ValueError):
            errors.append({"row": row, "code": "INVALID_AMOUNT"})
        parent = values.get("hierarchy_parent_row")
        if parent:
            if int(parent) >= row or int(parent) not in by_row:
                errors.append({"row": row, "code": "INVALID_PARENT"})
            else:
                children.setdefault(int(parent), []).append(row)

    account_rows = [r for r, v in by_row.items() if v.get("source_row_role") == "ACCOUNT_SUMMARY"]
    selected = [
        r
        for r, v in by_row.items()
        if v.get("source_account_code") and not v.get("hierarchy_parent_row")
    ]
    codes = Counter(by_row[r]["source_account_code"] for r in selected)
    repeated = sorted(code for code, count in codes.items() if count > 1)
    # Account summaries can themselves be nested. An ancestor and descendant are never additive.
    overlap = []
    for row in account_rows:
        parent = by_row[row].get("hierarchy_parent_row")
        visited: set[int] = set()
        while parent and int(parent) in by_row and int(parent) not in visited:
            p = int(parent)
            visited.add(p)
            if p in account_rows:
                overlap.append({"parent": p, "child": row})
            parent = by_row[p].get("hierarchy_parent_row")

    def totals(ids: list[int]) -> dict[str, Decimal]:
        return {m: sum((amounts[r][m] for r in ids if r in amounts), Decimal(0)) for m in MEASURES}

    # Recognize a footer candidate only from full 6-measure presence and absence of identity.
    footer = [
        r
        for r, v in by_row.items()
        if not v.get("source_account_code")
        and not v.get("source_account_name")
        and not v.get("source_analytic_label")
        and v.get("source_outline_level") == "0"
        and all(v.get(m) not in (None, "") for m in MEASURES)
    ]
    aggregate = totals(selected)
    residuals = (
        {m: str(aggregate[m] - amounts[footer[0]][m]) for m in MEASURES}
        if len(footer) == 1 and footer[0] in amounts
        else {}
    )
    checks = []
    for parent, child_rows in children.items():
        if parent not in amounts or any(r not in amounts for r in child_rows):
            continue
        child_total = totals(child_rows)
        residual = {m: str(child_total[m] - amounts[parent][m]) for m in MEASURES}
        checks.append(
            {
                "parent_row": parent,
                "child_rows": child_rows,
                "state": "PASS" if all(Decimal(v) == 0 for v in residual.values()) else "RESIDUAL",
                "residuals": residual,
            }
        )
    naive = totals([r for r in by_row if r not in footer])
    blocked = bool(
        errors
        or repeated
        or not selected
        or not residuals
        or any(Decimal(v) != 0 for v in residuals.values())
    )
    return {
        "version": "1c-account-frontier/1",
        "state": "REVIEW_REQUIRED" if blocked else "RECONCILED_CANDIDATE",
        "authority_state": "MAPPED_CANDIDATE",
        "selected_rows": selected,
        "excluded_rows": [r for r in by_row if r not in selected],
        "source_total_rows": footer,
        "duplicate_account_codes": repeated,
        "ancestor_overlap": overlap,
        "errors": errors,
        "frontier_grain": "SOURCE_ROOT_SUMMARY",
        "account_depth_available": False,
        "account_totals": {m: str(v) for m, v in aggregate.items()},
        "source_total_residuals": residuals,
        "naive_sum_overstatement": {m: str(naive[m] - aggregate[m]) for m in MEASURES},
        "hierarchy_checks": checks,
        "policy": "Source root summaries only; all source details retained for drill. "
        "Root groups can net balances differently from account/detail rows. "
        "This frontier proves source totals, not mapped account reporting depth. "
        "Blank measures treated as empty source cells under this layout contract. "
        "Signed values preserved. Candidate requires approved source/context/account binding; "
        "analytical residuals block dimensional use independently of account totals.",
    }

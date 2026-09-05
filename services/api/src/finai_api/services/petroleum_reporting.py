"""Versioned legacy operating-report reconstruction, isolated from financial authority.

Only retained workbook evidence is read. Product aliases belong to this source-specific
migration contract; these are not universal account or IFRS rules.
"""

import re
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any

from finai_api.services.workbook_source import read_workbook

VERSION = "petroleum-operating-migration/1"
TOTALS = {"итог", "итого", "total", "grand total"}
GA_ACCOUNTS = {"7310.02.1", "7410", "7410.01", "8220.01.1", "9210"}
# Explicit bilingual alias candidates. Finance approval is required before production use.
ALIASES = {
    "wholesale.petrol": [
        "Euro Regular (Import)",
        "Premium (Re-export)",
        "Super (Re-export)",
        "ევრო რეგულარი (იმპორტი)",
        "პრემიუმი (რეექსპორტი)",
        "სუპერი (რეექსპორტი)",
    ],
    "wholesale.diesel": [
        "Diesel (Wholesale)",
        "Eurodiesel (Export)",
        "დიზელი (საბითუმო)",
        "ევროდიზელი (ექსპორტი)",
    ],
    "wholesale.bitumen": ["Bitumen (Wholesale)", "ბიტუმი (საბითუმო)"],
    "retail.petrol": ["Euro Regular", "Premium", "Super", "ევრო რეგულარი", "პრემიუმი", "სუპერი"],
    "retail.diesel": ["Diesel", "Euro Diesel", "დიზელი", "ევრო დიზელი"],
    "retail.cng": [
        "Natural Gas",
        "Natural Gas (Wholesale)",
        "ბუნებრივი აირი",
        "ბუნებრივი აირი (საბითუმო)",
    ],
    "retail.lpg": ["Liquid Gas (Only SGP !!!)", "თხევადი აირი (მხოლოდ SGP !!!)"],
}


def normalized(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def classify(label: str, kind: str) -> str:
    # Revenue labels explicitly carry source units. Do not merge or convert quantities.
    name = label.rsplit(",", 1)[0] if kind == "revenue" and "," in label else label
    key = normalized(name)
    if kind == "cogs" and key in {
        normalized("Euro Regular (Wholesale)"),
        normalized("ევრო რეგულარი (საბითუმო)"),
    }:
        return "wholesale.petrol"
    return next(
        (group for group, names in ALIASES.items() if key in {normalized(n) for n in names}),
        "other",
    )


def reconstruct(content: bytes) -> dict[str, Any]:
    book = read_workbook(content)
    sheets = {s["name"]: s["cells"] for s in book["sheets"]}
    if not {"Revenue Breakdown", "COGS Breakdown"}.issubset(sheets):
        raise ValueError("This calculation requires Revenue Breakdown and COGS Breakdown sheets")
    for sheet, expected in {
        "Revenue Breakdown": {"A1": "Product", "D1": "Net Revenue"},
        "COGS Breakdown": {"K1": "6", "L1": "7310", "O1": "8230"},
    }.items():
        if any(
            sheets[sheet].get(cell, {}).get("value") != value for cell, value in expected.items()
        ):
            raise ValueError(f"Unsupported {sheet} source contract; review the column mappings")
    findings: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    sums: dict[str, Decimal] = {}
    blocked: set[str] = set()

    def number(sheet: str, address: str, blank_zero: bool = False) -> Decimal:
        cell = sheets[sheet].get(address, {})
        raw = cell.get("value", "")
        if raw == "" and blank_zero:
            return Decimal(0)
        try:
            value = Decimal(raw)
            if cell.get("type") == "e" or not value.is_finite() or abs(value) >= Decimal("1e24"):
                raise ValueError("Invalid amount")
            return value
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{sheet}!{address}: amount unavailable") from exc

    with localcontext() as context:
        context.prec = 50
        for kind, sheet in (("revenue", "Revenue Breakdown"), ("cogs", "COGS Breakdown")):
            rows = sorted(
                int(a[1:])
                for a in sheets[sheet]
                if a.startswith("A") and a[1:].isdigit() and int(a[1:]) > 1
            )
            for row in rows:
                label = sheets[sheet][f"A{row}"]["value"]
                if not label.strip() or normalized(label) in TOTALS:
                    continue
                group = classify(label, kind)
                metric = f"{kind}.{group}"
                try:
                    coordinates = (
                        [f"B{row}", f"C{row}"]
                        if kind == "revenue"
                        else [f"K{row}", f"L{row}", f"O{row}"]
                    )
                    if kind == "revenue":
                        source_cell = sheets[sheet].get(f"D{row}", {})
                        formula = source_cell.get("formula")
                        attributes = source_cell.get("formula_attributes", {})
                        if formula == "" and attributes.get("t") == "shared":
                            for address, anchor in sheets[sheet].items():
                                master = anchor.get("formula_attributes", {})
                                bounds = re.fullmatch(r"D(\d+):D(\d+)", master.get("ref", ""))
                                if (
                                    bounds
                                    and master.get("si") == attributes.get("si")
                                    and int(bounds[1]) <= row <= int(bounds[2])
                                    and address == f"D{bounds[1]}"
                                    and anchor["formula"] == f"B{bounds[1]}-C{bounds[1]}"
                                ):
                                    formula = f"B{row}-C{row}"
                                    break
                        if formula != f"B{row}-C{row}":
                            raise ValueError(f"{sheet}!D{row}: unsupported revenue formula")
                        value = number(sheet, f"B{row}", True) - number(sheet, f"C{row}", True)
                    else:
                        value = sum((number(sheet, c, True) for c in coordinates), Decimal(0))
                    sums[metric] = sums.get(metric, Decimal(0)) + value
                    facts.append(
                        {
                            "source_sheet": sheet,
                            "source_row": row,
                            "label": label,
                            "metric": metric,
                            "amount": str(value),
                            "coordinates": [f"{sheet}!{c}" for c in coordinates],
                            "mapping_state": "PROPOSED",
                            "grain": "PRODUCT_REVENUE_ROW"
                            if kind == "revenue"
                            else "PRODUCT_CORRESPONDING_ACCOUNT_ROW",
                        }
                    )
                except ValueError as exc:
                    blocked.add(metric)
                    findings.append(
                        {"code": "SOURCE_AMOUNT_UNAVAILABLE", "message": str(exc), "metric": metric}
                    )
        metrics: dict[str, dict[str, Any]] = {}

        def leaf(code: str) -> None:
            metrics[code] = {
                "id": code,
                "amount": None if code in blocked else str(sums.get(code, Decimal(0))),
                "state": "UNAVAILABLE" if code in blocked else "REFERENCE_CALCULATED",
                "dependencies": [
                    f"row:{f['source_sheet']}:{f['source_row']}"
                    for f in facts
                    if f["metric"] == code
                ],
            }

        def derived(code: str, terms: list[tuple[str, int]]) -> None:
            available = all(metrics[key]["amount"] is not None for key, _ in terms)
            metrics[code] = {
                "id": code,
                "amount": str(
                    sum((Decimal(metrics[key]["amount"]) * sign for key, sign in terms), Decimal(0))
                )
                if available
                else None,
                "state": "REFERENCE_CALCULATED" if available else "UNAVAILABLE",
                "dependencies": [key for key, _ in terms],
                "expression": terms,
            }

        for kind in ("revenue", "cogs"):
            for group in [*ALIASES, "other"]:
                leaf(f"{kind}.{group}")
            for segment in ("wholesale", "retail"):
                derived(
                    f"{kind}.{segment}",
                    [
                        (f"{kind}.{group}", 1)
                        for group in ALIASES
                        if group.startswith(segment + ".")
                    ],
                )
            derived(f"{kind}.total", [(f"{kind}.wholesale", 1), (f"{kind}.retail", 1)])
            derived(f"{kind}.including_other", [(f"{kind}.total", 1), (f"{kind}.other", 1)])
        derived("gross_profit", [("revenue.including_other", 1), ("cogs.including_other", -1)])
        metrics["ga"] = {
            "id": "ga",
            "amount": None,
            "state": "UNAVAILABLE",
            "dependencies": [],
            "reason": "Base company/period/currency and exact debit-account mapping "
            "must be bound before combining sources",
        }
        derived("legacy_ebitda", [("gross_profit", 1), ("ga", -1)])
        comparisons = []
        for metric, sheet, cell in [
            ("revenue.total", "Budget (2)", "B2"),
            ("cogs.total", "Budget (2)", "B17"),
            ("revenue.including_other", "Revenue Breakdown", "D36"),
        ]:
            if sheet not in sheets or cell not in sheets[sheet]:
                continue
            try:
                legacy = number(sheet, cell)
                computed = metrics[metric]["amount"]
                comparisons.append(
                    {
                        "metric": metric,
                        "coordinate": f"{sheet}!{cell}",
                        "legacy_cached": str(legacy),
                        "calculated": computed,
                        "difference": str(Decimal(computed) - legacy)
                        if computed is not None
                        else None,
                    }
                )
            except ValueError:
                findings.append({"code": "COMPARISON_UNAVAILABLE", "message": f"{sheet}!{cell}"})
    return {
        "contract_version": VERSION,
        "source_sha256": sha256(content).hexdigest(),
        "state": "REFERENCE_ONLY",
        "explanation": "Deterministic reconstruction using proposed legacy product aliases. "
        "Company, period, currency and accounting authority are not established by this "
        "calculation. It does not publish actual financial results.",
        "metrics": list(metrics.values()),
        "facts": facts,
        "comparisons": comparisons,
        "findings": findings,
        "mapping": {
            "version": VERSION,
            "aliases": ALIASES,
            "cogs_columns": ["K", "L", "O"],
            "ga_debit_accounts": sorted(GA_ACCOUNTS),
        },
        "missing_requirements": [
            "Reviewed source company/period/currency",
            "Approved canonical Product/Segment mapping",
            "Petroleum expense evidence or approved cross-company allocation/recharge, "
            "with reporting perimeter and duplicate-cost checks",
            "Reviewed COGS versus G&A overlap",
            "MR V8 report-definition and metric mapping",
        ],
    }

"""Recognize 1C account configuration by headers, retaining every source designation."""

import re
from collections import Counter
from typing import Any


def profile_accounts(sheet: dict[str, Any]) -> dict[str, Any] | None:
    rows: dict[int, dict[str, dict[str, Any]]] = {}
    for address, cell in sheet["cells"].items():
        match = re.fullmatch(r"([A-Z]+)(\d+)", address)
        if match:
            rows.setdefault(int(match[2]), {})[match[1]] = cell
    columns = {}
    header_row = 0
    for index, cells in sorted(rows.items()):
        if index > 30:
            break
        proposed = {str(cell["value"]).strip().casefold(): col for col, cell in cells.items()}
        if {"код", "наименование", "субконто 1"}.issubset(proposed):
            columns, header_row = proposed, index
            break
    if not columns:
        return None
    accounts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for index, cells in sorted(rows.items()):
        if index <= header_row:
            continue

        def value(header: str, row_cells: dict[str, Any] = cells) -> str:
            return str(row_cells.get(columns.get(header, ""), {}).get("value", "")).strip()

        code, name = value("код"), value("наименование")
        if not code and not name:
            continue
        coordinate = f"{sheet['name']}!{columns['код']}{index}"
        formulas = [
            f"{sheet['name']}!{col}{index}"
            for col, cell in cells.items()
            if cell.get("formula") is not None
        ]
        if not code or not name or formulas:
            findings.append(
                {
                    "code": "ACCOUNT_DEFINITION_REQUIRES_REVIEW",
                    "coordinates": [coordinate, *formulas],
                }
            )
        accounts.append(
            {
                "account_code": code,
                "source_name": name,
                "source_row": index,
                "coordinate": coordinate,
                "quick_selection": value("быстрый выбор"),
                "off_balance_source": value("заб."),
                "balance_behavior_source": value("акт."),
                "currency_tracking_source": value("вал."),
                "quantity_tracking_source": value("кол."),
                "analytics": [
                    {
                        "position": slot,
                        "source_label": value(f"субконто {slot}"),
                        "coordinate": f"{sheet['name']}!{columns[f'субконто {slot}']}{index}",
                    }
                    for slot in range(1, 4)
                    if f"субконто {slot}" in columns and value(f"субконто {slot}")
                ],
                "financial_mapping": "UNESTABLISHED",
                "required_dimension_policy": "UNESTABLISHED",
            }
        )
    counts = Counter(account["account_code"] for account in accounts)
    for code, count in counts.items():
        if count > 1:
            findings.append(
                {
                    "code": "DUPLICATE_ACCOUNT_CODE",
                    "account_code": code,
                    "coordinates": [a["coordinate"] for a in accounts if a["account_code"] == code],
                }
            )
    return {
        "sheet": sheet["name"],
        "header_row": header_row,
        "accounts": accounts,
        "findings": findings,
        "account_count": len(accounts),
        "semantics": "SOURCE_ACCOUNT_CONFIGURATION",
        "company_binding": "UNESTABLISHED",
        "policy": (
            "Source analytical labels and balance flags are retained verbatim. "
            "Their presence does not prove mandatory posting dimensions, IFRS classification "
            "or report-line membership."
        ),
    }

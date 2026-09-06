"""Observe a supported recorder-line workbook without assigning accounting authority."""

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from finai_api.services.workbook_source import read_workbook
from finai_api.services.workspace import WorkspaceError

REQUIRED = {
    "Period",
    "Line number",
    "Recorder",
    "Организация",
    "Account Dr",
    "Account Cr",
    "Сумма",
    "Валюта Dr",
    "Валютная сумма Dr",
    "Валюта Cr",
    "Валютная сумма Cr",
}
NUMERIC_OBSERVATIONS = {
    "Сумма": "source_amount",
    "Amount": "annotated_amount",
    "Валютная сумма Dr": "debit_currency_amount",
    "Валютная сумма Cr": "credit_currency_amount",
    "Количество Dr": "debit_quantity",
    "Количество Cr": "credit_quantity",
    "VAT": "annotated_vat",
}
TEXT_TYPES = {"s", "inlineStr", "str"}


def _literal_text(cell: dict[str, Any], coordinate: str) -> str:
    if cell["formula"] is not None or cell["type"] not in TEXT_TYPES or not cell["value"].strip():
        raise WorkspaceError(422, f"Literal source text required at {coordinate}")
    return str(cell["value"])


def _number(cell: dict[str, Any]) -> str | None:
    # A cached formula is retained as evidence, never recomputed or treated as a literal.
    if cell["type"] != "n" or not cell["value"]:
        return None
    try:
        value = Decimal(cell["value"])
    except InvalidOperation:
        return None
    # Preserve the exact source numeral, including exponent notation. Expanding
    # an untrusted exponent would allocate beyond the workbook's byte bound.
    return str(cell["value"]) if value.is_finite() else None


def read_base(content: bytes, sheet: str = "Base") -> dict[str, Any]:
    """Return source observations; no amount/currency/ledger mapping is authorized here."""
    try:
        book = read_workbook(content)
    except (ValueError, KeyError) as exc:
        raise WorkspaceError(422, f"Unsupported source workbook: {exc}") from exc
    matches = [item for item in book["sheets"] if item["name"] == sheet]
    if len(matches) != 1:
        raise WorkspaceError(422, "Select one unambiguous retained source sheet")
    source = matches[0]
    rows: dict[int, dict[str, Any]] = defaultdict(dict)
    for coordinate, cell in source["cells"].items():
        match = re.fullmatch(r"([A-Z]+)([0-9]+)", coordinate)
        assert match is not None
        rows[int(match[2])][match[1]] = cell
    headers = rows.get(1, {})
    by_label: dict[str, str] = {}
    for column, cell in headers.items():
        label = cell["value"]
        if label in REQUIRED | NUMERIC_OBSERVATIONS.keys():
            _literal_text(cell, f"{sheet}!{column}1")
            if label in by_label:
                raise WorkspaceError(422, f"Ambiguous source header: {label}")
            by_label[label] = column
    if not REQUIRED.issubset(by_label):
        raise WorkspaceError(422, "Source headers do not establish the recorder-line profile")
    result = []
    companies: set[str] = set()
    dates = []
    currencies: dict[str, list[dict[str, Any]]] = {"debit": [], "credit": []}
    findings = []
    for row_number, cells in sorted(rows.items()):
        if row_number == 1:
            continue

        def text(label: str, cells: dict[str, Any] = cells, row_number: int = row_number) -> str:
            column = by_label[label]
            cell = cells.get(column)
            coordinate = f"{sheet}!{column}{row_number}"
            if cell is None:
                raise WorkspaceError(422, f"Missing source value at {coordinate}")
            return _literal_text(cell, coordinate)

        company = text("Организация")
        companies.add(company)
        source_date = text("Period")
        try:
            observed = datetime.strptime(source_date, "%d.%m.%Y %H:%M:%S")
        except ValueError as exc:
            raise WorkspaceError(422, f"Unsupported source date at row {row_number}") from exc
        dates.append(observed.date())
        line_cell = cells.get(by_label["Line number"])
        line = _number(line_cell) if line_cell else None
        if (
            line is None
            or line_cell is None
            or line_cell["formula"] is not None
            or Decimal(line) < 1
            or Decimal(line) != Decimal(line).to_integral_value()
        ):
            raise WorkspaceError(
                422, f"Literal positive recorder line required at row {row_number}"
            )
        attrs = {
            "posting_date": observed.date().isoformat(),
            "source_row_key": f"{sheet}!{row_number}",
            "account_code": text("Account Dr"),
            "credit_account_code": text("Account Cr"),
            "source_family": "SEG_EXPENSE_BASE",
            "source_company_label": company,
            "source_recorder": text("Recorder"),
            "source_line_number": line,
        }
        numeric = {}
        for label, name in NUMERIC_OBSERVATIONS.items():
            observation_column = by_label.get(label)
            cell = cells.get(observation_column) if observation_column else None
            if cell is None:
                continue
            value = _number(cell)
            coordinate = f"{sheet}!{observation_column}{row_number}"
            numeric[name] = {
                "header": label,
                "coordinate": coordinate,
                **cell,
                "literal_decimal": value if cell["formula"] is None else None,
                "cached_decimal": value if cell["formula"] is not None else None,
                "accounting_role": "UNRESOLVED",
            }
            if value is None:
                findings.append({"coordinate": coordinate, "code": "NON_NUMERIC_OBSERVATION"})
        for side, label in (("debit", "Валюта Dr"), ("credit", "Валюта Cr")):
            column = by_label[label]
            cell = cells.get(column)
            if cell is not None:
                currencies[side].append(
                    {
                        "coordinate": f"{sheet}!{column}{row_number}",
                        **cell,
                        "role": "SOURCE_SIDE_CURRENCY_LABEL",
                    }
                )
        result.append(
            {
                "row": row_number,
                "attributes": attrs,
                "numeric_observations": numeric,
                "cells": {f"{sheet}!{column}{row_number}": cell for column, cell in cells.items()},
            }
        )
    if not result or len(companies) != 1:
        raise WorkspaceError(422, "Source scope requires rows with one explicit company label")
    return {
        "profile": "recorder-line-observations/1",
        "source_sha256": sha256(content).hexdigest(),
        "sheet": sheet,
        "company_label": next(iter(companies)),
        "rows": result,
        "headers": {f"{sheet}!{column}1": cell for column, cell in headers.items()},
        "sheet_state": source["state"],
        "merged_ranges": source["merged_ranges"],
        "defined_names": book["defined_names"],
        "external_dependencies": book["external_dependencies"],
        "observed_from": min(dates).isoformat(),
        "observed_through": max(dates).isoformat(),
        "evidence_granularity": "SOURCE_ROW",
        "deepest_valid_drill": "SOURCE_ROW",
        "currency_observations": currencies,
        "findings": findings,
        "accounting_mapping_available": False,
        "amount_mapping": None,
        "unresolved": [
            "Canonical company, chart, ledger and accounting book require accepted bindings.",
            "The source amount and annotated Amount are distinct observations; their accounting "
            "and gross/net/VAT meanings require an accepted source contract.",
            "Debit/credit currency labels do not establish the source amount's currency or "
            "functional/reporting currency; a blank label is not GEL.",
            "Dimension positions and translated/report labels do not establish canonical "
            "party, department or expense classification identities.",
            "Source timestamps have no declared timezone; dates are observed calendar dates.",
            "Rows do not establish complete journals, period completeness or certification.",
        ],
    }

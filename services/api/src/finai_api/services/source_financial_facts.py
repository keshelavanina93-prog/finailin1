"""Canonical source observations: journal movements and TB rows are distinct grains."""

import calendar
import re
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from uuid import UUID, uuid5

import xlrd

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.source_account_binding import account_code, observe_usage
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError
from finai_api.services.xls_source import FIELDS, MONTHS, cell_text


def decimal_cell(sheet, row, column):
    cell = sheet.cell(row, column)
    if cell.ctype != xlrd.XL_CELL_NUMBER:
        raise WorkspaceError(
            422, f"Numeric source amount required at row {row + 1}, column {column + 1}"
        )
    value = Decimal(str(cell.value))
    if not value.is_finite():
        raise WorkspaceError(422, "A source amount is not finite")
    return format(value, "f")


@lru_cache(maxsize=2)
def _read_rows_cached(content: bytes, sheet_name: str, profile: str) -> dict:
    usage = observe_usage(content, sheet_name, profile)
    book = xlrd.open_workbook(file_contents=content, formatting_info=True, on_demand=True)
    try:
        sheet = book.sheet_by_name(sheet_name)
        result = []
        if profile == "1c_tb":
            for field, column in FIELDS.items():
                if sheet.cell_value(6, column) != (
                    "Дебет" if field.endswith("debit") else "Кредит"
                ):
                    raise WorkspaceError(422, "Trial-balance measure headers changed")
            for column, label in [
                (6, "Сальдо на начало периода"),
                (10, "Оборот за период"),
                (14, "Сальдо на конец периода"),
            ]:
                if sheet.cell_value(5, column) != label:
                    raise WorkspaceError(422, "Trial-balance balance/movement headers changed")
            period = str(sheet.cell_value(2, 2))
            annual = re.fullmatch(r"Период: (\d{4}) \u0433\.", period)
            monthly = re.fullmatch(r"Период: (\w+) (\d{4}) \u0433\.", period)
            if annual:
                start, end = date(int(annual[1]), 1, 1), date(int(annual[1]), 12, 31)
            elif monthly and monthly[1] in MONTHS:
                year, month = int(monthly[2]), MONTHS.index(monthly[1]) + 1
                start, end = (
                    date(year, month, 1),
                    date(year, month, calendar.monthrange(year, month)[1]),
                )
            else:
                raise WorkspaceError(
                    422, "The source does not establish a supported accounting period"
                )
            stack = []
            for row in range(7, sheet.nrows):
                if not any(v != "" for v in sheet.row_values(row)):
                    continue
                level = sheet.rowinfo_map[row].outline_level if row in sheet.rowinfo_map else 0
                while stack and stack[-1][0] >= level:
                    stack.pop()
                code = account_code(book, sheet, row, 2) if sheet.cell_value(row, 2) != "" else ""
                role = (
                    ("ACCOUNT_GROUP" if "X" in code.upper() else "ACCOUNT_SUMMARY")
                    if code
                    else ("ANALYTICAL_ROW" if sheet.cell_value(row, 4) != "" else "UNRESOLVED_ROW")
                )
                attrs = {
                    "period_start": str(start),
                    "period_end": str(end),
                    "source_row_role": role,
                }
                if stack:
                    attrs["parent_source_row_key"] = f"{sheet_name}!{stack[-1][1]}"
                attrs.update(
                    {
                        field: decimal_cell(sheet, row, column)
                        for field, column in FIELDS.items()
                        if sheet.cell_value(row, column) != ""
                    }
                )
                stack.append((level, row + 1))
                result.append(
                    {
                        "row": row + 1,
                        "account_code": code if role == "ACCOUNT_SUMMARY" else "",
                        "attributes": attrs,
                    }
                )
        else:
            for row in range(2, sheet.nrows):
                if not any(v != "" for v in sheet.row_values(row)):
                    continue
                try:
                    observed_date = datetime.strptime(
                        str(sheet.cell_value(row, 6)), "%d.%m.%Y %H:%M:%S"
                    ).date()
                    components = date(
                        int(sheet.cell_value(row, 5)),
                        int(sheet.cell_value(row, 4)),
                        int(sheet.cell_value(row, 3)),
                    )
                except (ValueError, TypeError) as exc:
                    raise WorkspaceError(422, "A journal row has an invalid source date") from exc
                if components != observed_date:
                    raise WorkspaceError(422, "Journal date fields disagree")
                reference = str(sheet.cell_value(row, 8)).strip()
                if not reference:
                    raise WorkspaceError(
                        422, "A journal movement requires its source document reference"
                    )
                result.append(
                    {
                        "row": row + 1,
                        "debit_code": account_code(book, sheet, row, 10),
                        "credit_code": account_code(book, sheet, row, 16),
                        "attributes": {
                            "posting_date": str(observed_date),
                            "document_reference": reference,
                            "amount": decimal_cell(sheet, row, 22),
                        },
                    }
                )
        account_rows = defaultdict(list)
        for item in result:
            if item.get("account_code"):
                account_rows[item["account_code"]].append(item["row"])
        duplicate_accounts = {code: rows for code, rows in account_rows.items() if len(rows) > 1}
        for item in result:
            row = item["row"] - 1
            item["attributes"].update(
                {
                    "source_row_key": f"{sheet_name}!{row + 1}",
                    "unit_status": "UNESTABLISHED",
                    "source_details": {
                        "cells": {
                            xlrd.colname(c): {
                                "type": sheet.cell_type(row, c),
                                "value": cell_text(sheet.cell_value(row, c)),
                            }
                            for c in range(sheet.ncols)
                        },
                        "parser": "source-accounting/1",
                        "currency_authority": "UNESTABLISHED",
                        "aggregation_policy": "NON_ADDITIVE_REVIEW_REQUIRED",
                        "same_account_source_rows": duplicate_accounts.get(
                            item.get("account_code"), []
                        ),
                    },
                }
            )
        return {
            "company_label": usage["company_label"],
            "rows": result,
            "duplicate_account_rows": duplicate_accounts,
            "object_type": "SourceTrialBalanceRow"
            if profile == "1c_tb"
            else "SourceJournalMovement",
        }
    finally:
        book.release_resources()


def read_rows(content: bytes, sheet_name: str, profile: str) -> dict:
    return deepcopy(_read_rows_cached(content, sheet_name, profile))


def prepare(
    principal: Principal, document_id: str, sheet: str, profile: str, company_id: UUID, offset: int
) -> dict:
    metadata, content = document_bytes(principal, document_id)
    parsed = _read_rows_cached(content, sheet, profile)
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"])
    company = resources.current_resources(principal, [company_id]).get(str(company_id))
    if (
        not company
        or company["authority_state"] != "APPROVED"
        or company["object_type"] != "LegalEntity"
        or company["evidence_class"] != "SOURCE_BOUND"
        or company["attributes"].get("evidence_id") != str(evidence)
        or company["display_name"] != parsed["company_label"]
    ):
        raise WorkspaceError(409, "Select the reviewed company from this source")
    chart = uuid5(company_id, "1c-observed-chart")
    selected = parsed["rows"][offset : offset + 25]
    ids = {
        uuid5(chart, item[field])
        for item in selected
        for field in ("account_code", "debit_code", "credit_code")
        if item.get(field)
    }
    heads = resources.current_resources(principal, list(ids))
    accounts = {}
    rows = []
    for item in selected:
        attrs = deepcopy(item["attributes"])
        attrs.update(
            {
                "legal_entity_id": str(company_id),
                "evidence_id": str(evidence),
                "source_family": profile + ":" + metadata["source_sha256"] + ":" + sheet,
            }
        )
        for code_field, target in [
            ("account_code", "account_id"),
            ("debit_code", "debit_account_id"),
            ("credit_code", "credit_account_id"),
        ]:
            code = item.get(code_field)
            if not code:
                continue
            if code not in accounts:
                accepted = heads.get(str(uuid5(chart, code)))
                if (
                    not accepted
                    or accepted["authority_state"] != "APPROVED"
                    or accepted["object_type"] != "LocalAccount"
                    or accepted["attributes"].get("chart_id") != str(chart)
                    or accepted["attributes"].get("account_code") != code
                ):
                    raise WorkspaceError(409, "Accepted company account binding is inconsistent")
                accounts[code] = accepted
            attrs[target] = accounts[code]["resource_id"]
        coordinate = f"{sheet}!row:{item['row']}"
        record = uuid5(evidence, coordinate)
        attrs["source_record_id"] = str(record)
        rows.append(
            {
                "resource_id": str(uuid5(evidence, parsed["object_type"] + ":" + coordinate)),
                "record_id": str(record),
                "coordinate": coordinate,
                "attributes": attrs,
            }
        )
    published = resources.current_resources(principal, [UUID(row["resource_id"]) for row in rows])
    for row in rows:
        accepted = published.get(row["resource_id"])
        row["publication_state"] = (
            "UNPUBLISHED"
            if not accepted
            else (
                "APPROVED"
                if accepted["authority_state"] == "APPROVED"
                and accepted["evidence_class"] == "SOURCE_BOUND"
                and accepted["object_type"] == parsed["object_type"]
                and accepted["attributes"] == row["attributes"]
                else "REVIEW_REQUIRED"
            )
        )
        row["published_version_id"] = accepted["version_id"] if accepted else None
    return {
        "document_id": document_id,
        "source_sha256": metadata["source_sha256"],
        "object_type": parsed["object_type"],
        "total_rows": len(parsed["rows"]),
        "offset": offset,
        "next_offset": offset + 25 if offset + 25 < len(parsed["rows"]) else None,
        "rows": rows,
        "duplicate_account_rows": deepcopy(parsed["duplicate_account_rows"]),
        "financial_publication_status": "CURRENCY_AND_LEDGER_UNESTABLISHED",
    }


def propose(
    principal: Principal, document_id: str, sheet: str, profile: str, company_id: UUID, offset: int
):
    page = prepare(principal, document_id, sheet, profile, company_id, offset)
    mutations = []
    existing = resources.current_resources(
        principal, [UUID(row[key]) for row in page["rows"] for key in ("record_id", "resource_id")]
    )
    for row in page["rows"]:
        for identity, kind, name, attrs in [
            (
                row["record_id"],
                "SourceRecord",
                row["coordinate"],
                {"coordinate": row["coordinate"], "evidence_id": row["attributes"]["evidence_id"]},
            ),
            (row["resource_id"], page["object_type"], row["coordinate"], row["attributes"]),
        ]:
            prior = existing.get(identity)
            if prior:
                if (
                    prior["attributes"] != attrs
                    or prior["object_type"] != kind
                    or prior["authority_state"] != "APPROVED"
                    or prior["evidence_class"] != "SOURCE_BOUND"
                ):
                    raise WorkspaceError(
                        409, "Published source observation differs; review a new parser version"
                    )
                continue
            mutations.append(
                ResourceMutation(
                    resource_id=UUID(identity),
                    object_type=kind,
                    identity_key="source-fact:" + identity,
                    display_name=name,
                    attributes=attrs,
                    evidence_class="SOURCE_BOUND",
                    valid_from=datetime.now(UTC),
                )
            )
    if not mutations:
        raise WorkspaceError(409, "This source fact page is empty or already published")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Publish typed source accounting observations",
            rationale="Retain each original row with exact company/account dependencies. "
            "Journal movement, account summaries, analytics and controls remain distinct. "
            "Currency, ledger authority and overlapping-source reconciliation are unestablished; "
            "these observations do not create postings or report totals.",
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
        ),
    )

"""Bounded OOXML evidence inspection. Formulas and external links are never executed."""

import io
import json
import posixpath
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from hashlib import sha256
from typing import Any
from zipfile import BadZipFile, ZipFile

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ingest import Candidate, IngestReceipt, IngestRequest

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
REF = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][\w. ]*))!\$?([A-Z]{1,3})\$?(\d*)")
ACCOUNT = re.compile(r"\d[\d.Xx]*(?:/\d+)?")


def read_workbook(content: bytes) -> dict[str, Any]:
    if not 0 < len(content) <= 16_000_000:
        raise ValueError("Workbook exceeds 16 MB")
    try:
        archive = ZipFile(io.BytesIO(content))
    except BadZipFile as exc:
        raise ValueError("Invalid XLSX archive") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > 3000 or sum(e.file_size for e in entries) > 80_000_000:
            raise ValueError("Workbook expanded-size limit exceeded")
        if len({e.filename for e in entries}) != len(entries):
            raise ValueError("Duplicate workbook archive members")

        def xml(path: str) -> ET.Element:
            try:
                data = archive.read(path)
                if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                    raise ValueError("XML entity declarations are unsupported")
                return ET.fromstring(data)
            except (KeyError, ET.ParseError) as exc:
                raise ValueError("Invalid workbook XML part") from exc

        workbook = xml("xl/workbook.xml")
        rels = {r.attrib["Id"]: r.attrib for r in xml("xl/_rels/workbook.xml.rels")}
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(t.text or "" for t in item.iterfind(".//s:t", NS))
                for item in xml("xl/sharedStrings.xml")
            ]
        sheets = []
        cell_count = 0
        for sheet in workbook.findall("s:sheets/s:sheet", NS):
            rel = rels.get(sheet.attrib[RID], {})
            if rel.get("TargetMode") == "External":
                raise ValueError("External worksheet cannot be read")
            target = rel.get("Target", "")
            path = posixpath.normpath(
                target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
            )
            if not path.startswith("xl/worksheets/"):
                raise ValueError("Unsupported worksheet part")
            root = xml(path)
            cells: dict[str, dict[str, Any]] = {}
            for row in root.findall("s:sheetData/s:row", NS):
                for c in row.findall("s:c", NS):
                    address = c.get("r", "")
                    if not re.fullmatch(r"[A-Z]{1,3}[1-9]\d{0,6}", address):
                        raise ValueError("Invalid cell coordinate")
                    value = c.findtext("s:v", default="", namespaces=NS)
                    kind = c.get("t", "n")
                    if kind == "s":
                        try:
                            value = strings[int(value)]
                        except (ValueError, IndexError) as exc:
                            raise ValueError("Invalid shared string") from exc
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iterfind(".//s:t", NS))
                    formula = c.find("s:f", NS)
                    if value == "" and formula is None:
                        continue
                    cell_count += 1
                    if cell_count > 250_000:
                        raise ValueError("Workbook exceeds 250000 populated cells")
                    if address in cells:
                        raise ValueError("Duplicate cell coordinate")
                    cells[address] = {
                        "value": value,
                        "type": kind,
                        "formula": formula.text or "" if formula is not None else None,
                        "formula_attributes": dict(formula.attrib) if formula is not None else {},
                        "outline_level": int(row.get("outlineLevel", "0")),
                        "style_id": c.get("s", "0"),
                    }
            sheets.append(
                {
                    "name": sheet.get("name", ""),
                    "state": sheet.get("state", "visible"),
                    "cells": cells,
                    "merged_ranges": [
                        m.get("ref") for m in root.findall("s:mergeCells/s:mergeCell", NS)
                    ],
                }
            )
        names = [
            {"name": n.get("name"), "scope": n.get("localSheetId"), "formula": n.text or ""}
            for n in workbook.findall("s:definedNames/s:definedName", NS)
        ]
        external: list[str] = []
        for entry in entries:
            if entry.filename.startswith("xl/externalLinks/_rels/"):
                external.extend(
                    r.get("Target", "")
                    for r in xml(entry.filename)
                    if r.get("TargetMode") == "External"
                )
        return {"sheets": sheets, "defined_names": names, "external_dependencies": external}


def profile_workbook(book: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    summaries = []
    edges: Counter[tuple[str, str]] = Counter()
    sheet_names = {s["name"] for s in book["sheets"]}

    def finding(code: str, sheet: str, message: str, coordinates: list[str]) -> None:
        findings.append(
            {
                "code": code,
                "sheet": sheet,
                "message": message,
                "coordinates": coordinates[:30],
                "occurrences": len(coordinates),
                "severity": "REVIEW_REQUIRED",
            }
        )

    for sheet in book["sheets"]:
        cells = sheet["cells"]
        name = sheet["name"]
        headers = {a: c["value"] for a, c in cells.items() if re.fullmatch(r"[A-Z]+1", a)}
        header_values = set(headers.values())
        source_type = "OTHER_TABULAR"
        grain = "SOURCE_CELL"
        if {"Period", "Recorder", "Account Dr", "Account Cr"} <= header_values:
            source_type, grain = "GL_OR_JOURNAL", "RECORDER_LINE"
        elif {"Product", "Net Revenue", "VAT"} <= header_values:
            source_type, grain = "PRODUCT_REVENUE", "PRODUCT_PERIOD"
        elif {"Субконто", "Деб. оборот", "Кред. оборот"} <= header_values:
            source_type, grain = (
                "ACCOUNT_ANALYTIC_TURNOVER",
                "ANALYTIC_CORRESPONDING_ACCOUNT_PERIOD",
            )
        elif sum(
            bool(ACCOUNT.fullmatch(c["value"])) and "/" in c["value"]
            for a, c in cells.items()
            if re.fullmatch(r"B\d+", a)
        ) >= 3 and any(c["value"].strip() for a, c in cells.items() if re.fullmatch(r"[EF]\d+", a)):
            source_type, grain = "MAPPING_TABLE", "LOCAL_ACCOUNT_ANALYTIC"
        elif any(c["formula"] is not None for c in cells.values()):
            source_type = "WORKBOOK_MODEL_OR_REPORT"
        periods: set[str] = set()
        companies: set[str] = set()
        currencies: set[str] = set()
        rows: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        errors = []
        formulas = 0
        for address, c in cells.items():
            column, row = re.fullmatch(r"([A-Z]+)(\d+)", address).groups()  # type: ignore[union-attr]
            rows[int(row)][column] = c
            if c["type"] == "e":
                errors.append(address)
            if c["formula"] is not None:
                formulas += 1
                for quoted, unquoted, _, _ in REF.findall(c["formula"]):
                    dependency = (quoted or unquoted).replace("''", "'")
                    if dependency != name:
                        edges[(dependency, name)] += 1
                if "#REF!" in c["formula"]:
                    errors.append(address)
        if source_type == "GL_OR_JOURNAL":
            columns = {value: re.sub(r"\d", "", a) for a, value in headers.items()}
            keys: dict[tuple[str, str, str], list[str]] = defaultdict(list)
            for row, values in rows.items():
                if row == 1:
                    continue

                def val(
                    key: str, values: dict[str, Any] = values, columns: dict[str, str] = columns
                ) -> str:
                    return str(values.get(columns.get(key, ""), {}).get("value", ""))

                date = re.match(r"\d{2}\.(\d{2})\.(\d{4})(?: |$)", val("Period"))
                if date:
                    periods.add(f"{date[2]}-{date[1]}")
                if val("Организация"):
                    companies.add(val("Организация"))
                for currency in (val("Валюта Dr"), val("Валюта Cr")):
                    if currency:
                        currencies.add(currency)
                key = (val("Организация"), val("Recorder"), val("Line number"))
                keys[key].append(f"A{row}")
            duplicate_rows = [
                a for key, addresses in keys.items() if len(addresses) > 1 for a in addresses
            ]
            if duplicate_rows:
                finding(
                    "REPEATED_TRANSACTION_KEY",
                    name,
                    "Repeated company/recorder/line keys require source identity "
                    "review; do not silently deduplicate.",
                    duplicate_rows,
                )
            finding(
                "AMOUNT_AUTHORITY_REVIEW",
                name,
                "Ledger amount, foreign currency amounts, quantities, adjusted amount "
                "and VAT are distinct measures. Formula-derived classifications are "
                "not posted ledger facts.",
                ["S1", "AD1", "AN1"],
            )
        if source_type == "MAPPING_TABLE":
            codes: dict[str, list[str]] = defaultdict(list)
            summary_rows = []
            unmapped = []
            for row, values in rows.items():
                code = values.get("B", {}).get("value", "")
                if not code:
                    continue
                codes[code].append(f"B{row}")
                if "/" not in code:
                    summary_rows.append(f"B{row}")
                elif not all(
                    values.get(col, {}).get("value", "").strip() for col in ("C", "E", "F")
                ):
                    unmapped.append(f"B{row}")
            repeated = [a for addresses in codes.values() if len(addresses) > 1 for a in addresses]
            if repeated:
                finding(
                    "ACCOUNT_CODE_NOT_UNIQUE",
                    name,
                    "Mapping key must include account and analytic label plus approved"
                    " scope/version. Account alone repeats.",
                    repeated,
                )
            if summary_rows:
                finding(
                    "SUBTOTAL_DETAIL_OVERLAP",
                    name,
                    "Account/group amounts coexist with analytic mappings. No additive"
                    " use until hierarchy and coverage are reviewed.",
                    summary_rows,
                )
            if unmapped:
                finding(
                    "INCOMPLETE_MAPPING",
                    name,
                    "Analytic rows have missing mapping dimensions or report targets.",
                    unmapped,
                )
        if errors:
            finding(
                "WORKBOOK_ERROR_CELLS",
                name,
                "Source contains error cells or broken formula references; affected "
                "mappings/outputs are unresolved.",
                sorted(set(errors)),
            )
        totals = [
            a
            for a, c in cells.items()
            if c["formula"] is None
            and c["value"].strip().casefold() in {"итог", "итого", "total", "grand total"}
        ]
        if totals:
            finding(
                "SUBTOTAL_DETAIL_OVERLAP",
                name,
                "Total rows coexist with detail; totals are controls, not additional facts.",
                totals,
            )
        if not periods and source_type in {
            "GL_OR_JOURNAL",
            "MAPPING_TABLE",
            "PRODUCT_REVENUE",
            "ACCOUNT_ANALYTIC_TURNOVER",
        }:
            finding(
                "PERIOD_UNESTABLISHED",
                name,
                "No recognized posting-period evidence in this sheet. Filename and "
                "inherited names do not establish fact period.",
                [],
            )
        # A sheet content identity detects copies independently of workbook filename and style.
        identity = sha256(
            json.dumps(
                [
                    (a, c["value"], c["type"], c["formula"], c["formula_attributes"])
                    for a, c in sorted(cells.items())
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        summaries.append(
            {
                "sheet": name,
                "state": sheet["state"],
                "source_type": source_type,
                "grain": grain,
                "populated_cells": len(cells),
                "source_rows": len(rows),
                "formula_count": formulas,
                "content_sha256": identity,
                "observed_values_sha256": sha256(json.dumps(
                    [(a, c["value"], "text" if c["type"] in {"s", "str", "inlineStr"}
                      else c["type"]) for a, c in sorted(cells.items())],
                    ensure_ascii=False).encode()).hexdigest(),
                "periods": sorted(periods),
                "company_labels": sorted(companies),
                "transaction_currencies": sorted(currencies),
                "functional_currency": None,
                "reporting_unit": None,
            }
        )
    broken = [n["name"] for n in book["defined_names"] if "#REF!" in n["formula"]]
    if broken:
        finding(
            "BROKEN_DEFINED_NAMES",
            "",
            "Legacy defined names contain broken references. Determine reachability "
            "before blocking an output.",
            broken,
        )
    if book["external_dependencies"]:
        finding(
            "EXTERNAL_DEPENDENCIES",
            "",
            "External workbook links are retained but never opened. Active output "
            "dependencies require supplied, governed sources.",
            book["external_dependencies"],
        )
    report_context = {}
    by_name = {s["name"]: s["cells"] for s in book["sheets"]}
    cover = by_name.get("Cover", {})
    segment = by_name.get("Segment_map", {})
    if cover.get("C3", {}).get("value", "").startswith("Please Select Period"):
        report_context = {
            "month_label": cover.get("L3", {}).get("value"),
            "year": cover.get("O3", {}).get("value"),
            "company_label": segment.get("D4", {}).get("value"),
            "currency": segment.get("J4", {}).get("value"),
            "coordinates": ["Cover!L3", "Cover!O3", "Segment_map!D4", "Segment_map!J4"],
            "semantics": "TEMPLATE_SELECTION_NOT_FACT_AUTHORITY",
        }
    return {
        "version": "workbook-source-profile/1",
        "sheets": summaries,
        "report_context": report_context,
        "findings": findings,
        "dependencies": [
            {"source": a, "target": b, "formula_count": n, "resolved_sheet": a in sheet_names}
            for (a, b), n in sorted(edges.items())
        ],
        "defined_name_count": len(book["defined_names"]),
        "external_dependencies": book["external_dependencies"],
        "formula_policy": "RETAIN_ONLY_NO_EXECUTION",
        "financial_promotion": "UNAVAILABLE",
    }


def compile_workbook(request: IngestRequest) -> IngestReceipt:
    from finai_api.services.ingestion import SourceAuthorityDenied

    if (
        set(request.requested_objects) - {"SourceRecord"}
        or request.context_version_id
        or request.account_version_ids
        or request.account_alias_version_ids
    ):
        raise SourceAuthorityDenied(
            "Workbook observations require reviewed semantic contracts before financial binding"
        )
    content = request.source_bytes()
    book = read_workbook(content)
    profile = profile_workbook(book)
    profile["source_use"] = request.source_use
    candidates = []
    for sheet in book["sheets"]:
        rows: dict[int, dict[str, str]] = defaultdict(dict)
        for address, cell in sheet["cells"].items():
            row = int(re.search(r"\d+", address)[0])  # type: ignore[index]
            rows[row][address] = json.dumps(cell, ensure_ascii=False, sort_keys=True)
        for row, values in sorted(rows.items()):
            candidates.append(
                Candidate(
                    object_type="SourceRecord",
                    source_row=row,
                    epistemic_state="OBSERVED",
                    values={
                        "source_sheet": sheet["name"],
                        "aggregation_policy": "NON_ADDITIVE_REVIEW_REQUIRED",
                        **values,
                    },
                )
            )
    periods = sorted({p for s in profile["sheets"] for p in s["periods"]})
    companies = sorted({p for s in profile["sheets"] for p in s["company_labels"]})
    rejects = tuple(
        f"Observed period {p} differs from requested {request.scope.period}"
        for p in periods
        if p != request.scope.period and request.source_use == "ACTUAL_INPUT"
    )
    request_hash = canonical_sha256(request)
    return IngestReceipt(
        receipt_id=f"ir_{request_hash}",
        request_sha256=request_hash,
        source_sha256=sha256(content).hexdigest(),
        scope=request.scope,
        source_class="WORKBOOK_PACKAGE",
        source_profile=profile,
        classifier_version="ooxml-structural/1",
        authority_contract_version="workbook-observations/1",
        pack_version="workbook-source/1",
        plan=("preserve", "classify", "profile", "validate", "candidates"),
        observed_bindings={
            "period": ", ".join(periods) or "UNESTABLISHED",
            "company_label": ", ".join(companies) or "UNESTABLISHED",
        },
        used_fields=(
            "cell_value",
            "formula",
            "cached_value",
            "source_coordinate",
            "sheet",
            "defined_names",
            "external_links",
        ),
        unused_fields=(),
        candidates=tuple(candidates),
        rejects=rejects,
        warnings=(
            "Observed labels are not canonical company/currency bindings.",
            "Formulas and cached values are retained without execution or certification.",
            "Source-only evidence cannot populate certified reports.",
        ),
        reconciliation={"status": "REVIEW_REQUIRED", "aggregation": "NOT_PERFORMED"},
        functions_executed=("source.ooxml-inspection/1",),
    )


def preview_workbook(content: bytes, offset: int, search: str) -> dict[str, Any]:
    book = read_workbook(content)
    rows: list[dict[str, Any]] = [
        {
            "source_row": i + 1,
            "values": [s["name"], a, c["value"], c["formula"] or ""],
            "width_matches_header": True,
        }
        for s in book["sheets"]
        for i, (a, c) in enumerate(s["cells"].items())
    ]
    matching = [
        r for r in rows if not search or any(search.casefold() in v.casefold() for v in r["values"])
    ]
    return {
        "columns": ["Sheet", "Cell", "Cached/source value", "Formula (not executed)"],
        "rows": matching[offset : offset + 100],
        "total_rows": len(rows),
        "matching_rows": len(matching),
        "offset": offset,
        "page_size": 100,
        "has_more": len(matching) > offset + 100,
        "sha256": sha256(content).hexdigest(),
        "byte_length": len(content),
        "integrity": "VERIFIED",
        "value_semantics": "SOURCE_CACHED_XLSX_CELLS",
        "profile": [],
        "extra_width_rows": 0,
        "profile_scope": "ENTIRE_SOURCE",
    }

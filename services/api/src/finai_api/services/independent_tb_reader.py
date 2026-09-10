"""Independent Decimal reader for 1C account-period trial balances.

This module intentionally has no dependency on :mod:`xls_source`.  It is an
oracle-side reader for source-control proofs and recurring-family diagnostics;
it does not create journal entries, currency facts, or accounting authority.

The reader preserves empty cells as ``None``.  Diagnostic arithmetic uses zero
only for the signed balance/rollforward checks, matching the independent audit
policy.  All numeric values are converted to ``Decimal(str(decoded_value))``
before any arithmetic.
"""

from __future__ import annotations

import json
import re
from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import xlrd

MEASURES = (
    "opening_debit",
    "opening_credit",
    "turnover_debit",
    "turnover_credit",
    "closing_debit",
    "closing_credit",
)

# These are deliberately local constants.  The production source parser is a
# separate implementation and must not be used as the audit reader.
MEASURE_COLUMNS: Mapping[str, int] = {
    "opening_debit": 6,  # G
    "opening_credit": 7,  # H
    "turnover_debit": 10,  # K
    "turnover_credit": 13,  # N
    "closing_debit": 14,  # O
    "closing_credit": 16,  # Q
}
MEASURE_COORDINATES: Mapping[str, str] = {
    "opening_debit": "G",
    "opening_credit": "H",
    "turnover_debit": "K",
    "turnover_credit": "N",
    "closing_debit": "O",
    "closing_credit": "Q",
}
MONTHS = (
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
)
SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
PERIOD_RE = re.compile(r"Период: (\w+) (\d{4}) \u0433\.")

OutlineRole = Literal["root", "parent", "detail", "subkonto", "control", "footer", "unresolved"]
Materiality = Literal["IMMATERIAL", "MATERIAL"]


class TBReaderError(ValueError):
    """The workbook does not satisfy the reviewed 1C layout contract."""


class TBControlMismatch(TBReaderError):
    """A month disagrees with its frozen independent control expectation."""

    def __init__(self, month: str, failures: Sequence[str]):
        self.month = month
        self.failures = tuple(failures)
        super().__init__(f"{month}: independent TB control mismatch: {', '.join(self.failures)}")


def _text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decimal(value: Any, *, coordinate: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TBReaderError(f"{coordinate}: amount is not a Decimal") from exc
    if not result.is_finite():
        raise TBReaderError(f"{coordinate}: amount is not finite")
    return result


def _zero(value: Decimal | None) -> Decimal:
    return Decimal(0) if value is None else value


def _net(row: TBRow, opening_or_closing: Literal["opening", "closing"]) -> Decimal:
    return _zero(row.amounts[f"{opening_or_closing}_debit"]) - _zero(
        row.amounts[f"{opening_or_closing}_credit"]
    )


def _period(value: str) -> tuple[str, date, date]:
    match = PERIOD_RE.fullmatch(value)
    if match is None or match[1] not in MONTHS:
        raise TBReaderError("C3: the workbook does not establish a recognized monthly period")
    year, month = int(match[2]), MONTHS.index(match[1]) + 1
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return f"{year:04d}-{month:02d}", start, end


@dataclass(frozen=True, slots=True)
class TBRow:
    """One retained source row with raw coordinates and Decimal measures."""

    source_row: int
    account_code: str | None
    account_name: str | None
    subkonto: str | None
    outline_level: int
    outline_role: OutlineRole
    parent_row: int | None
    parent_code: str | None
    amounts: Mapping[str, Decimal | None]
    coordinates: Mapping[str, str]
    source_cells: tuple[str | None, ...]
    account_path: tuple[str, ...] = ()
    additive_ok: bool = True
    duplicate_of: int | None = None
    overlap_reason: str | None = None

    def amount(self, measure: str, *, empty_as_zero: bool = False) -> Decimal | None:
        value = self.amounts[measure]
        return _zero(value) if empty_as_zero else value

    @property
    def identity_key(self) -> str | None:
        if not self.account_code:
            return None
        return "/".join(self.account_path or (self.account_code,))


@dataclass(frozen=True, slots=True)
class TBControl:
    source_row: int
    amounts: Mapping[str, Decimal]
    coordinates: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class TBFingerprint:
    """Stable family shape excluding the observed month heading."""

    digest: str
    measure_columns: tuple[tuple[str, int], ...]
    outline_levels: tuple[int, ...]
    outline_shape: tuple[tuple[int, int], ...]
    account_codes: tuple[str, ...]
    heading_language: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "measure_columns": [list(item) for item in self.measure_columns],
            "outline_levels": list(self.outline_levels),
            "outline_shape": [list(item) for item in self.outline_shape],
            "account_codes": list(self.account_codes),
            "heading_language": list(self.heading_language),
        }


@dataclass(frozen=True, slots=True)
class TBMonth:
    filename: str
    source_sha256: str
    sheet: str
    company_heading: str
    title_heading: str
    period_heading: str
    data_mode_heading: str
    period: str
    period_start: date
    period_end: date
    rows: tuple[TBRow, ...]
    control: TBControl
    fingerprint: TBFingerprint

    @property
    def nonblank_row_count(self) -> int:
        return len(self.rows)

    @property
    def root_rows(self) -> tuple[TBRow, ...]:
        return tuple(row for row in self.rows if row.outline_role == "root")

    @property
    def coded_rows(self) -> tuple[TBRow, ...]:
        return tuple(row for row in self.rows if row.account_code is not None)

    @property
    def account_codes(self) -> tuple[str, ...]:
        return tuple(sorted({row.account_code for row in self.coded_rows if row.account_code}))

    def root_totals(self) -> dict[str, Decimal]:
        return {
            measure: sum(
                (_zero(row.amounts[measure]) for row in self.root_rows),
                Decimal(0),
            )
            for measure in MEASURES
        }

    def rollforward_failures(self) -> tuple[tuple[int, str, Decimal], ...]:
        failures = []
        for row in self.root_rows:
            residual = (
                _zero(row.amounts["opening_debit"])
                - _zero(row.amounts["opening_credit"])
                + _zero(row.amounts["turnover_debit"])
                - _zero(row.amounts["turnover_credit"])
                - _zero(row.amounts["closing_debit"])
                + _zero(row.amounts["closing_credit"])
            )
            if residual != 0:
                failures.append((row.source_row, row.account_code or "", residual))
        return tuple(failures)


@dataclass(frozen=True, slots=True)
class TBAuditExpectation:
    filename: str
    period: str
    nonblank_rows: int
    root_rows: int
    opening: Decimal
    turnover: Decimal
    closing: Decimal
    control_row: int


@dataclass(frozen=True, slots=True)
class TBControlProof:
    month: TBMonth
    expected: TBAuditExpectation
    root_totals: Mapping[str, Decimal]
    pair_equality: Mapping[str, bool]
    rollforward_failures: tuple[tuple[int, str, Decimal], ...]

    @property
    def status(self) -> Literal["PASS", "MISMATCH"]:
        return "PASS" if not self.failures() else "MISMATCH"

    def failures(self) -> tuple[str, ...]:
        month = self.month
        expected = self.expected
        failures: list[str] = []
        if month.filename != expected.filename:
            failures.append(f"filename={month.filename!r}")
        if month.period != expected.period:
            failures.append(f"period={month.period!r}")
        if month.nonblank_row_count != expected.nonblank_rows:
            failures.append(f"rows={month.nonblank_row_count} expected={expected.nonblank_rows}")
        if len(month.root_rows) != expected.root_rows:
            failures.append(f"roots={len(month.root_rows)} expected={expected.root_rows}")
        if month.control.source_row != expected.control_row:
            failures.append(
                f"control_row={month.control.source_row} expected={expected.control_row}"
            )
        for measure, expected_value in {
            "opening_debit": expected.opening,
            "opening_credit": expected.opening,
            "turnover_debit": expected.turnover,
            "turnover_credit": expected.turnover,
            "closing_debit": expected.closing,
            "closing_credit": expected.closing,
        }.items():
            if month.control.amounts[measure] != expected_value:
                failures.append(
                    f"{measure}={month.control.amounts[measure]} expected={expected_value}"
                )
        failures.extend(
            f"{group}_debit_credit_unequal"
            for group, equal in self.pair_equality.items()
            if not equal
        )
        failures.extend(
            f"root_rollforward row={row} code={code} residual={residual}"
            for row, code, residual in self.rollforward_failures
        )
        for group in ("opening", "turnover", "closing"):
            debit = self.root_totals[f"{group}_debit"]
            credit = self.root_totals[f"{group}_credit"]
            if debit != credit:
                failures.append(f"root_{group}_debit_credit_unequal")
        for measure in MEASURES:
            if self.root_totals[measure] != month.control.amounts[measure]:
                failures.append(
                    f"root_{measure}={self.root_totals[measure]} "
                    f"control={month.control.amounts[measure]}"
                )
        return tuple(failures)


@dataclass(frozen=True, slots=True)
class TBSchemaDelta:
    from_period: str
    to_period: str
    new_account_codes: tuple[str, ...]
    removed_account_codes: tuple[str, ...]
    new_outline_levels: tuple[int, ...]
    removed_outline_levels: tuple[int, ...]
    outline_shape_changed: bool
    measure_columns_changed: bool
    heading_language_changed: bool

    @property
    def requires_review(self) -> bool:
        return bool(
            self.new_account_codes
            or self.removed_account_codes
            or self.new_outline_levels
            or self.removed_outline_levels
            or self.outline_shape_changed
            or self.measure_columns_changed
            or self.heading_language_changed
        )

    @property
    def auto_reuse_existing_classification(self) -> bool:
        return not self.measure_columns_changed and not self.heading_language_changed


@dataclass(frozen=True, slots=True)
class ContinuityBreak:
    period_from: str
    period_to: str
    account_code: str
    prior_close: Decimal
    next_open: Decimal
    delta: Decimal
    materiality: Materiality
    scope: Literal["CONTROL", "ROOT", "ACCOUNT"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "period_from": self.period_from,
            "period_to": self.period_to,
            "account_code": self.account_code,
            "prior_close": format(self.prior_close, "f"),
            "next_open": format(self.next_open, "f"),
            "delta": format(self.delta, "f"),
            "materiality": self.materiality,
            "scope": self.scope,
        }


def _heading_language(values: Sequence[str]) -> tuple[str, ...]:
    scripts: set[str] = set()
    for value in values:
        if re.search(r"[\u0410-\u042f\u0430-\u044f\u0401\u0451]", value):
            scripts.add("CYRILLIC")
        if re.search(r"[ა-ჰ]", value):
            scripts.add("GEORGIAN")
        if re.search(r"[A-Za-z]", value):
            scripts.add("LATIN")
    return tuple(sorted(scripts))


def _fingerprint(
    *,
    measure_columns: Mapping[str, int],
    outline_levels: Sequence[int],
    account_codes: Sequence[str],
    heading_values: Sequence[str],
) -> TBFingerprint:
    outline_shape = tuple(
        sorted((level, outline_levels.count(level)) for level in set(outline_levels))
    )
    heading_language = _heading_language(heading_values)
    payload = {
        "measure_columns": sorted(measure_columns.items()),
        "outline_levels": sorted(set(outline_levels)),
        "outline_shape": outline_shape,
        "account_codes": sorted(set(account_codes)),
        "heading_language": heading_language,
    }
    digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return TBFingerprint(
        digest=digest,
        measure_columns=tuple(sorted(measure_columns.items())),
        outline_levels=tuple(sorted(set(outline_levels))),
        outline_shape=outline_shape,
        account_codes=tuple(sorted(set(account_codes))),
        heading_language=heading_language,
    )


def _is_nonblank(values: Sequence[Any]) -> bool:
    return any(value != "" for value in values)


def _has_footer_marker(values: Sequence[Any]) -> bool:
    return any("Ответственный" in _text(value) for value in values if value != "")


def _row_role(
    *,
    account_code: str | None,
    subkonto: str | None,
    outline_level: int,
    has_children: bool,
    is_control: bool,
    is_footer: bool,
) -> OutlineRole:
    if is_control:
        return "control"
    if is_footer:
        return "footer"
    if account_code:
        if outline_level == 0:
            return "root"
        return "parent" if has_children else "detail"
    if subkonto:
        return "subkonto"
    return "unresolved"


def read_tb(
    content: bytes,
    *,
    filename: str = "<memory>",
    expected_sheet: str | None = "TDSheet",
) -> TBMonth:
    """Read one 1C workbook independently and retain all source coordinates."""

    if not 0 < len(content) <= 4_000_000 or not content.startswith(SIGNATURE):
        raise TBReaderError("Unsupported XLS source")
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True, formatting_info=True)
    except Exception as exc:  # xlrd raises several implementation-specific errors.
        raise TBReaderError("The XLS workbook could not be read") from exc
    try:
        if book.nsheets != 1:
            raise TBReaderError("The independent reader requires one worksheet")
        sheet = book.sheet_by_index(0)
        if expected_sheet is not None and sheet.name != expected_sheet:
            raise TBReaderError(f"Expected worksheet {expected_sheet!r}, found {sheet.name!r}")
        if not 8 <= sheet.nrows <= 10000 or not 17 <= sheet.ncols <= 32:
            raise TBReaderError("Unrecognized 1C trial balance layout")
        if any(
            sheet.cell_value(row, column) != ""
            for row in range(sheet.nrows)
            for column in range(17, sheet.ncols)
        ):
            raise TBReaderError("Additional populated XLS columns require adapter review")

        expected_headers = {
            (1, 2): "Оборотно-сальдовая ведомость",
            (6, 2): "Код",
            (6, 3): "Наименование",
            (5, 6): "Сальдо на начало периода",
            (5, 10): "Оборот за период",
            (5, 14): "Сальдо на конец периода",
        }
        expected_headers.update(
            {
                (6, column): "Дебет" if measure.endswith("debit") else "Кредит"
                for measure, column in MEASURE_COLUMNS.items()
            }
        )
        for (row, column), expected in expected_headers.items():
            if sheet.cell_value(row, column) != expected:
                coordinate = f"{xlrd.colname(column)}{row + 1}"
                raise TBReaderError(f"{coordinate}: expected {expected!r}")

        company_heading = _text(sheet.cell_value(0, 2))
        title_heading = _text(sheet.cell_value(1, 2))
        period_heading = _text(sheet.cell_value(2, 2))
        data_mode_heading = _text(sheet.cell_value(3, 2))
        period, period_start, period_end = _period(period_heading)

        source_rows: list[dict[str, Any]] = []
        footer_rows: set[int] = set()
        for row in range(7, sheet.nrows):
            values = tuple(sheet.row_values(row)[:17])
            if not _is_nonblank(values):
                continue
            source_row = row + 1
            if _has_footer_marker(values):
                footer_rows.add(source_row)
            account_code = _text(values[2]) or None
            account_name = _text(values[3]) or None
            subkonto = _text(values[4]) or None
            outline_level = (
                sheet.rowinfo_map[row].outline_level if row in sheet.rowinfo_map else 0
            )
            amounts = {
                measure: _decimal(
                    values[column],
                    coordinate=f"{sheet.name}!{MEASURE_COORDINATES[measure]}{source_row}",
                )
                for measure, column in MEASURE_COLUMNS.items()
            }
            source_rows.append(
                {
                    "source_row": source_row,
                    "account_code": account_code,
                    "account_name": account_name,
                    "subkonto": subkonto,
                    "outline_level": outline_level,
                    "amounts": amounts,
                    "source_cells": tuple(
                        _text(value) if value != "" else None for value in values
                    ),
                }
            )

        # Identify the source control before building row roles.  It is a
        # diagnostic control, not an account-period fact.
        candidates = [
            row
            for row in source_rows
            if row["source_row"] not in footer_rows
            and row["account_code"] is None
            and row["account_name"] is None
            and row["subkonto"] is None
            and row["outline_level"] == 0
            and all(row["amounts"][measure] is not None for measure in MEASURES)
        ]
        if len(candidates) != 1:
            raise TBReaderError(
                f"Expected one unlabeled six-measure control row, found {len(candidates)}"
            )
        control_row = candidates[0]
        control = TBControl(
            source_row=control_row["source_row"],
            amounts={
                measure: control_row["amounts"][measure]
                for measure in MEASURES
                if control_row["amounts"][measure] is not None
            },
            coordinates={
                measure: f"{sheet.name}!{MEASURE_COORDINATES[measure]}{control_row['source_row']}"
                for measure in MEASURES
            },
        )

        # Build the source outline independently.  Parent pointers are source
        # row coordinates; no account-code join is used for hierarchy.
        stack: list[tuple[int, int, str | None]] = []
        provisional: list[dict[str, Any]] = []
        for source_item in source_rows:
            while stack and stack[-1][0] >= source_item["outline_level"]:
                stack.pop()
            parent_row = stack[-1][1] if stack else None
            parent_code = stack[-1][2] if stack else None
            path = tuple(
                code for _, _, code in stack if code
            ) + ((source_item["account_code"],) if source_item["account_code"] else ())
            enriched = {
                **source_item,
                "parent_row": parent_row,
                "parent_code": parent_code,
                "account_path": path,
            }
            provisional.append(enriched)
            stack.append(
                (
                    source_item["outline_level"],
                    source_item["source_row"],
                    source_item["account_code"],
                )
            )

        children = {
            provisional_item["source_row"]: any(
                item["parent_row"] == provisional_item["source_row"]
                for item in provisional
            )
            for provisional_item in provisional
        }
        rows: list[TBRow] = []
        for provisional_item in provisional:
            is_control = provisional_item["source_row"] == control.source_row
            role = _row_role(
                account_code=provisional_item["account_code"],
                subkonto=provisional_item["subkonto"],
                outline_level=provisional_item["outline_level"],
                has_children=children[provisional_item["source_row"]],
                is_control=is_control,
                is_footer=provisional_item["source_row"] in footer_rows,
            )
            rows.append(
                TBRow(
                    source_row=provisional_item["source_row"],
                    account_code=provisional_item["account_code"],
                    account_name=provisional_item["account_name"],
                    subkonto=provisional_item["subkonto"],
                    outline_level=provisional_item["outline_level"],
                    outline_role=role,
                    parent_row=provisional_item["parent_row"],
                    parent_code=provisional_item["parent_code"],
                    amounts=provisional_item["amounts"],
                    coordinates={
                        measure: (
                            f"{sheet.name}!{MEASURE_COORDINATES[measure]}"
                            f"{provisional_item['source_row']}"
                        )
                        for measure in MEASURES
                    },
                    source_cells=provisional_item["source_cells"],
                    account_path=provisional_item["account_path"],
                )
            )

        heading_values = [
            _text(sheet.cell_value(row, column))
            for row, column in (
                (0, 2),
                (1, 2),
                (3, 2),
                (5, 6),
                (5, 10),
                (5, 14),
                (6, 6),
                (6, 7),
                (6, 10),
                (6, 13),
                (6, 14),
                (6, 16),
            )
        ]
        fingerprint = _fingerprint(
            measure_columns=MEASURE_COLUMNS,
            outline_levels=[row.outline_level for row in rows],
            account_codes=[row.account_code for row in rows if row.account_code],
            heading_values=heading_values,
        )
        return TBMonth(
            filename=filename,
            source_sha256=sha256(content).hexdigest(),
            sheet=sheet.name,
            company_heading=company_heading,
            title_heading=title_heading,
            period_heading=period_heading,
            data_mode_heading=data_mode_heading,
            period=period,
            period_start=period_start,
            period_end=period_end,
            rows=tuple(rows),
            control=control,
            fingerprint=fingerprint,
        )
    finally:
        book.release_resources()


def read_tb_path(path: str | Path, *, expected_sheet: str | None = "TDSheet") -> TBMonth:
    source = Path(path)
    return read_tb(source.read_bytes(), filename=source.name, expected_sheet=expected_sheet)


def verify_control(month: TBMonth, expected: TBAuditExpectation) -> TBControlProof:
    """Verify one month and raise immediately on any mismatch."""

    pair_equality = {
        group: month.control.amounts[f"{group}_debit"]
        == month.control.amounts[f"{group}_credit"]
        for group in ("opening", "turnover", "closing")
    }
    proof = TBControlProof(
        month=month,
        expected=expected,
        root_totals=month.root_totals(),
        pair_equality=pair_equality,
        rollforward_failures=month.rollforward_failures(),
    )
    failures = proof.failures()
    if failures:
        raise TBControlMismatch(month.period, failures)
    return proof


def read_audit_fixture(
    paths: Sequence[str | Path], expectations: Mapping[str, TBAuditExpectation]
) -> tuple[TBControlProof, ...]:
    """Read ordered fixture files and fail closed at the first mismatch."""

    months = sorted(
        (read_tb_path(Path(item)) for item in paths),
        key=lambda item: item.period,
    )
    proofs: list[TBControlProof] = []
    for month in months:
        expected = expectations.get(month.period)
        if expected is None:
            raise TBControlMismatch(month.period, ("no frozen audit expectation",))
        proofs.append(verify_control(month, expected))
    return tuple(proofs)


def schema_delta(previous: TBMonth, current: TBMonth) -> TBSchemaDelta:
    """Return review-only drift; existing classification can be reused safely
    when measure columns and heading language remain compatible.
    """

    old, new = previous.fingerprint, current.fingerprint
    return TBSchemaDelta(
        from_period=previous.period,
        to_period=current.period,
        new_account_codes=tuple(sorted(set(new.account_codes) - set(old.account_codes))),
        removed_account_codes=tuple(sorted(set(old.account_codes) - set(new.account_codes))),
        new_outline_levels=tuple(sorted(set(new.outline_levels) - set(old.outline_levels))),
        removed_outline_levels=tuple(sorted(set(old.outline_levels) - set(new.outline_levels))),
        outline_shape_changed=old.outline_shape != new.outline_shape,
        measure_columns_changed=old.measure_columns != new.measure_columns,
        heading_language_changed=old.heading_language != new.heading_language,
    )


def family_deltas(months: Sequence[TBMonth]) -> tuple[TBSchemaDelta, ...]:
    return tuple(schema_delta(previous, current) for previous, current in pairwise(months))


def mark_overlaps(
    month: TBMonth, *, account_prefixes: Sequence[str] = ("7410",)
) -> TBMonth:
    """Mark known hierarchy overlaps while retaining every source row.

    This is a parameterized source-shape diagnostic.  The default is the
    audit's 7410 fixture pattern; no company name, currency, or financial
    classification is inferred.  Root rows remain canonical for source-total
    aggregation and overlapping descendants point to that surviving root.
    """

    prefixes = tuple(account_prefixes)
    updated: list[TBRow] = []
    canonical_by_root: dict[str, int] = {}
    row_to_root: dict[int, str] = {}
    for row in month.rows:
        if row.outline_role == "root" and row.account_code:
            canonical_by_root[row.account_code] = row.source_row
        if row.account_path:
            row_to_root[row.source_row] = row.account_path[0]
    for row in month.rows:
        root = row_to_root.get(row.source_row)
        if not root or not any(root.startswith(prefix) for prefix in prefixes):
            updated.append(row)
            continue
        canonical = canonical_by_root.get(root)
        if canonical is None or row.source_row == canonical:
            updated.append(row)
            continue
        updated.append(
            replace(
                row,
                additive_ok=False,
                duplicate_of=canonical,
                overlap_reason="OVERLAPPING_SOURCE_HIERARCHY",
            )
        )
    return replace(month, rows=tuple(updated))


def _code_net(
    month: TBMonth, *, closing_or_opening: Literal["closing", "opening"]
) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in month.coded_rows:
        assert row.account_code is not None
        totals[row.account_code] = totals.get(row.account_code, Decimal(0)) + _net(
            row, closing_or_opening
        )
    return totals


def continuity_breaks(
    months: Sequence[TBMonth], *, materiality_threshold: Decimal = Decimal("0.01")
) -> tuple[ContinuityBreak, ...]:
    """Compare closing → next opening at controls, roots and coded accounts.

    A blank side is zero only for this diagnostic.  Missing/new account codes
    therefore produce visible breaks rather than disappearing from the report.
    """

    if materiality_threshold < 0:
        raise ValueError("materiality threshold cannot be negative")
    ordered = tuple(sorted(months, key=lambda item: item.period))
    breaks: list[ContinuityBreak] = []
    for previous, current in pairwise(ordered):
        # The independent audit table records one boundary control per month.
        # Debit and credit are checked equal in B5; use the debit control as
        # the representative amount and retain that equality in the caller's
        # monthly proof rather than emitting two duplicate breaks.
        prior = previous.control.amounts["closing_debit"]
        following = current.control.amounts["opening_debit"]
        delta = following - prior
        if delta:
            breaks.append(
                ContinuityBreak(
                    period_from=previous.period,
                    period_to=current.period,
                    account_code="__CONTROL__",
                    prior_close=prior,
                    next_open=following,
                    delta=delta,
                    materiality="MATERIAL"
                    if abs(delta) > materiality_threshold
                    else "IMMATERIAL",
                    scope="CONTROL",
                )
            )
        previous_roots = {
            row.account_code: _net(row, "closing")
            for row in previous.root_rows
            if row.account_code
        }
        current_roots = {
            row.account_code: _net(row, "opening")
            for row in current.root_rows
            if row.account_code
        }
        for account_code in sorted(set(previous_roots) | set(current_roots)):
            prior = previous_roots.get(account_code, Decimal(0))
            following = current_roots.get(account_code, Decimal(0))
            delta = following - prior
            if delta:
                breaks.append(
                    ContinuityBreak(
                        period_from=previous.period,
                        period_to=current.period,
                        account_code=account_code,
                        prior_close=prior,
                        next_open=following,
                        delta=delta,
                        materiality="MATERIAL"
                        if abs(delta) > materiality_threshold
                        else "IMMATERIAL",
                        scope="ROOT",
                    )
                )
        previous_accounts = _code_net(previous, closing_or_opening="closing")
        current_accounts = _code_net(current, closing_or_opening="opening")
        for account_code in sorted(set(previous_accounts) | set(current_accounts)):
            prior = previous_accounts.get(account_code, Decimal(0))
            following = current_accounts.get(account_code, Decimal(0))
            delta = following - prior
            if delta:
                breaks.append(
                    ContinuityBreak(
                        period_from=previous.period,
                        period_to=current.period,
                        account_code=account_code,
                        prior_close=prior,
                        next_open=following,
                        delta=delta,
                        materiality="MATERIAL"
                        if abs(delta) > materiality_threshold
                        else "IMMATERIAL",
                        scope="ACCOUNT",
                    )
                )
    return tuple(breaks)

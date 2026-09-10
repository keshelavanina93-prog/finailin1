"""Compile the twelve SGP 2025 workbooks as one historical evidence package."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestReceipt, IngestRequest
from finai_api.domain.review import Principal
from finai_api.domain.trial_balance_package import (
    TrialBalanceCarryforward,
    TrialBalanceDiagnosticFinding,
    TrialBalanceMonthProof,
    TrialBalancePackageDiagnostics,
    TrialBalancePackageFile,
    TrialBalancePackageReport,
    TrialBalancePackageRequest,
)
from finai_api.services.ingestion import compile_source
from finai_api.services.tb_frontier import MEASURES, analyze
from finai_api.services.xls_source import inspect_xls


class TrialBalancePackageError(ValueError):
    """A package cannot be treated as a valid 2025 historical intake."""


def _decode(item: TrialBalancePackageFile) -> bytes:
    try:
        content = base64.b64decode(item.xls_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise TrialBalancePackageError(f"{item.filename}: invalid XLS encoding") from exc
    if not 0 < len(content) <= 4_000_000:
        raise TrialBalancePackageError(f"{item.filename}: XLS exceeds the 4 MB limit")
    return content


def _decimal(value: str | None) -> Decimal:
    try:
        parsed = Decimal(value or "0")
    except InvalidOperation as exc:
        raise TrialBalancePackageError("A trial balance amount is not a decimal") from exc
    if not parsed.is_finite():
        raise TrialBalancePackageError("A trial balance amount is not finite")
    return parsed


def _equality(
    frontier: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Literal["PASS", "BREAK"]], Literal["PASS", "BREAK"]]:
    totals = frontier.get("account_totals") or {}
    residuals = frontier.get("source_total_residuals") or {}
    pair_deltas = {
        group: str(_decimal(totals.get(f"{group}_debit")) - _decimal(totals.get(f"{group}_credit")))
        for group in ("opening", "turnover", "closing")
    }
    equality = {}
    for group in ("opening", "turnover", "closing"):
        pair_pass = _decimal(pair_deltas[group]) == 0
        for side in ("debit", "credit"):
            measure = f"{group}_{side}"
            equality[measure] = (
                "PASS"
                if pair_pass and measure in residuals and _decimal(residuals[measure]) == 0
                else "BREAK"
            )
    state: Literal["PASS", "BREAK"] = (
        "PASS" if equality and all(value == "PASS" for value in equality.values()) else "BREAK"
    )
    return pair_deltas, cast(dict[str, Literal["PASS", "BREAK"]], equality), state


def _carryforward(
    previous: TrialBalanceMonthProof | None, current: TrialBalanceMonthProof
) -> TrialBalanceCarryforward:
    if previous is None:
        return TrialBalanceCarryforward(
            from_period=None,
            to_period=current.period,
            opening_debit=current.totals.get("opening_debit"),
            prior_closing_debit=None,
            debit_delta=None,
            opening_credit=current.totals.get("opening_credit"),
            prior_closing_credit=None,
            credit_delta=None,
            state="NOT_APPLICABLE",
        )
    opening_debit = _decimal(current.totals.get("opening_debit"))
    prior_debit = _decimal(previous.totals.get("closing_debit"))
    opening_credit = _decimal(current.totals.get("opening_credit"))
    prior_credit = _decimal(previous.totals.get("closing_credit"))
    debit_delta = opening_debit - prior_debit
    credit_delta = opening_credit - prior_credit
    state: Literal["PASS", "BREAK"] = "PASS" if debit_delta == 0 and credit_delta == 0 else "BREAK"
    return TrialBalanceCarryforward(
        from_period=previous.period,
        to_period=current.period,
        opening_debit=str(opening_debit),
        prior_closing_debit=str(prior_debit),
        debit_delta=str(debit_delta),
        opening_credit=str(opening_credit),
        prior_closing_credit=str(prior_credit),
        credit_delta=str(credit_delta),
        state=state,
    )


def build_package_report(
    sources: Iterable[tuple[str, bytes, dict[str, Any], str | None]],
    *,
    currency: str,
    active_runtime_period: str,
    expected_row_count: int = 38137,
    tenant_id: str | None = None,
    legal_entity_id: str | None = None,
) -> TrialBalancePackageReport:
    """Build a deterministic package report from validated monthly sources.

    ``sources`` is ordered or unordered; the result is always ordered by the
    observed source period.  The runtime period is carried only as a guard and
    never used to reinterpret the historical evidence.
    """

    entries = sorted(sources, key=lambda item: item[2]["period"])
    if len(entries) != 12:
        raise TrialBalancePackageError("The 2025 package must contain exactly twelve workbooks")
    periods = [source[2]["period"] for source in entries]
    expected_periods = [f"2025-{month:02d}" for month in range(1, 13)]
    if periods != expected_periods:
        raise TrialBalancePackageError("The package must cover every 2025 month exactly once")
    labels = {source[2]["company_label"] for source in entries}
    if len(labels) != 1:
        raise TrialBalancePackageError("All workbooks must carry the same source company label")
    entity_label = next(iter(labels))
    folded_label = entity_label.casefold()
    if not (
        ("socar" in folded_label and "petrol" in folded_label)
        or ("სოკარ" in folded_label and "პეტრ" in folded_label)
        or ("сокар" in folded_label and "петрол" in folded_label)
    ):
        raise TrialBalancePackageError(
            "The SGP historical intake requires a SOCAR Petroleum source company label"
        )

    months: list[TrialBalanceMonthProof] = []
    with localcontext() as context:
        context.prec = 50
        for filename, content, source, receipt_id in entries:
            frontier = analyze(source["rows"])
            pair_deltas, equality, equality_state = _equality(frontier)
            hierarchy_checks = frontier.get("hierarchy_checks") or []
            months.append(
                TrialBalanceMonthProof(
                    filename=filename,
                    period=source["period"],
                    source_sha256=sha256(content).hexdigest(),
                    row_count=len(source["rows"]),
                    selected_root_rows=len(frontier.get("selected_rows", [])),
                    source_total_rows=tuple(frontier.get("source_total_rows", [])),
                    totals={
                        measure: str(frontier.get("account_totals", {}).get(measure, "0"))
                        for measure in MEASURES
                    },
                    pair_deltas=pair_deltas,
                    hierarchy_check_count=len(hierarchy_checks),
                    hierarchy_breaks=sum(
                        check.get("state") != "PASS" for check in hierarchy_checks
                    ),
                    equality=equality,
                    equality_state=equality_state,
                    receipt_id=receipt_id,
                )
            )

    carryforward = tuple(
        _carryforward(previous, current)
        for previous, current in zip([None, *months[:-1]], months, strict=True)
    )
    row_count = sum(month.row_count for month in months)
    package_key = {
        "year": 2025,
        "currency": currency,
        "company": entity_label,
        "tenant_id": tenant_id,
        "legal_entity_id": legal_entity_id,
        "sources": [(month.filename, month.source_sha256) for month in months],
    }
    package_id = (
        "tbp_"
        + sha256(
            json.dumps(package_key, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    equality_pass = all(month.equality_state == "PASS" for month in months)
    return TrialBalancePackageReport(
        package_id=package_id,
        tenant_id=cast(UUID | None, tenant_id),
        legal_entity_id=legal_entity_id,
        entity_label=entity_label,
        currency=currency,
        row_count=row_count,
        row_count_state="PASS" if row_count == expected_row_count else "BREAK",
        periods=tuple(periods),
        months=tuple(months),
        carryforward=carryforward,
        carryforward_breaks=sum(item.state == "BREAK" for item in carryforward),
        hierarchy_breaks=sum(month.hierarchy_breaks for month in months),
        package_evidence_state="SOURCE_PROOF_PASSED"
        if row_count == expected_row_count and equality_pass
        else "SOURCE_REVIEW_REQUIRED",
        historical_scope_guard={
            "source_year": "2025",
            "active_runtime_period": active_runtime_period,
            "evaluated_under_active_runtime_period": False,
            "period_binding": "SOURCE_PERIOD_PER_WORKBOOK",
        },
        account_codes=tuple(
            sorted(
                {
                    str(row["values"]["source_account_code"])
                    for _, _, source, _ in entries
                    for row in source["rows"]
                    if row["values"].get("source_account_code")
                }
            )
        ),
    )


def diagnose_package(
    report: TrialBalancePackageReport, scope: ExactScope
) -> TrialBalancePackageDiagnostics:
    """Return bounded package diagnostics without changing evidence or mappings."""

    if (
        report.tenant_id != scope.tenant_id
        or report.legal_entity_id != scope.legal_entity_id
        or report.currency != scope.currency
    ):
        raise TrialBalancePackageError(
            "Package is outside the authenticated tenant, entity and currency scope"
        )
    package_key = {
        "year": report.year,
        "currency": report.currency,
        "company": report.entity_label,
        "tenant_id": str(report.tenant_id) if report.tenant_id is not None else None,
        "legal_entity_id": report.legal_entity_id,
        "sources": [(month.filename, month.source_sha256) for month in report.months],
    }
    expected_package_id = (
        "tbp_"
        + sha256(
            json.dumps(package_key, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    if report.package_id != expected_package_id:
        raise TrialBalancePackageError("Package identity hash does not match its source manifest")

    expected_periods = tuple(f"2025-{month:02d}" for month in range(1, 13))
    guard = report.historical_scope_guard
    evaluated_under_active_runtime_period = bool(guard.get("evaluated_under_active_runtime_period"))
    guard_isolated = (
        report.year == 2025
        and report.periods == expected_periods
        and tuple(month.period for month in report.months) == expected_periods
        and guard.get("source_year") == "2025"
        and guard.get("active_runtime_period") == scope.period
        and guard.get("evaluated_under_active_runtime_period") is False
        and guard.get("period_binding") == "SOURCE_PERIOD_PER_WORKBOOK"
    )
    findings: list[TrialBalanceDiagnosticFinding] = []
    if guard_isolated:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="HISTORICAL_SCOPE_ISOLATED",
                severity="INFO",
                state="PASS",
                message=(
                    "Each workbook remains bound to its observed 2025 month; the active "
                    "runtime period is only diagnostic context."
                ),
                periods=expected_periods,
            )
        )
    else:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="HISTORICAL_SCOPE_REVIEW",
                severity="ERROR",
                state="BLOCKED",
                message=(
                    "The package period binding or active runtime guard does not prove "
                    "historical isolation."
                ),
                periods=report.periods,
            )
        )

    equality_breaks = tuple(
        month.period for month in report.months if month.equality_state != "PASS"
    )
    if equality_breaks:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="SOURCE_EQUALITY_BREAK",
                severity="ERROR",
                state="BLOCKED",
                message=(
                    "One or more monthly opening, turnover or closing equality proofs "
                    "require review."
                ),
                periods=equality_breaks,
            )
        )
    else:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="SOURCE_EQUALITY_PASS",
                severity="INFO",
                state="PASS",
                message="All monthly opening, turnover and closing debit-credit proofs pass.",
                periods=expected_periods,
            )
        )

    carryforward_breaks = tuple(
        item.to_period for item in report.carryforward if item.state == "BREAK"
    )
    if carryforward_breaks:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="CARRYFORWARD_REVIEW",
                severity="WARNING",
                state="REVIEW_REQUIRED",
                message=(
                    "Opening balances do not equal the prior month closing balances "
                    "for every transition."
                ),
                periods=carryforward_breaks,
            )
        )
    else:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="CARRYFORWARD_PASS",
                severity="INFO",
                state="PASS",
                message=(
                    "Every month-to-month opening balance matches the prior month closing balance."
                ),
                periods=expected_periods[1:],
            )
        )

    locks_enforced = report.finance_locked and report.planning_locked and report.reporting_locked
    if report.mapping_state == "REQUIRED" and locks_enforced:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="MAPPING_GATE_LOCKED",
                severity="INFO",
                state="LOCKED",
                message=(
                    "Finance, Planning and Reporting remain locked while account mappings "
                    "require approval."
                ),
            )
        )
    elif report.mapping_state == "REQUIRED":
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="MAPPING_GATE_BROKEN",
                severity="ERROR",
                state="BLOCKED",
                message="At least one downstream surface is unlocked before mapping approval.",
            )
        )
    else:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="MAPPING_STATE_UNVERIFIED",
                severity="WARNING",
                state="REVIEW_REQUIRED",
                message=(
                    "The report carries an approved mapping state; this diagnostic does "
                    "not grant or persist mapping approval."
                ),
            )
        )

    if report.package_evidence_state == "SOURCE_PROOF_PASSED":
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="PACKAGE_SOURCE_PROOF",
                severity="INFO",
                state="PASS",
                message=(
                    "The package reports source-total and row-count proof as passed; "
                    "retention is not re-proven by this diagnostic."
                ),
            )
        )
    else:
        findings.append(
            TrialBalanceDiagnosticFinding(
                code="PACKAGE_SOURCE_REVIEW",
                severity="WARNING",
                state="REVIEW_REQUIRED",
                message="The package-level source proof remains under review.",
            )
        )

    if any(item.severity == "ERROR" for item in findings):
        overall_state: Literal["PASS", "REVIEW_REQUIRED", "BLOCKED"] = "BLOCKED"
    elif (
        report.mapping_state != "APPROVED"
        or carryforward_breaks
        or report.package_evidence_state != "SOURCE_PROOF_PASSED"
    ):
        overall_state = "REVIEW_REQUIRED"
    else:
        overall_state = "PASS"
    return TrialBalancePackageDiagnostics(
        package_id=report.package_id,
        tenant_id=scope.tenant_id,
        legal_entity_id=scope.legal_entity_id,
        source_periods=report.periods,
        active_runtime_period=scope.period,
        evaluated_under_active_runtime_period=evaluated_under_active_runtime_period,
        historical_scope_state="ISOLATED" if guard_isolated else "REVIEW_REQUIRED",
        evidence_state=report.package_evidence_state,
        mapping_state=report.mapping_state,
        finance_locked=report.finance_locked,
        planning_locked=report.planning_locked,
        reporting_locked=report.reporting_locked,
        carryforward_breaks=report.carryforward_breaks,
        overall_state=overall_state,
        findings=tuple(findings),
    )


def compile_package(
    principal: Principal, request: TrialBalancePackageRequest
) -> TrialBalancePackageReport:
    """Compile and retain the package using each workbook's observed month.

    The caller's current period is deliberately never used as the source period.
    This is the boundary that prevents a 2025 package from being evaluated as
    an August 2026 operational source.
    """

    prepared: list[tuple[str, bytes, dict[str, Any], IngestReceipt]] = []
    seen_periods: set[str] = set()
    for item in request.files:
        content = _decode(item)
        try:
            source = inspect_xls(content)
        except ValueError as exc:
            raise TrialBalancePackageError(f"{item.filename}: {exc}") from exc
        expected_month = int(item.filename.removesuffix(".xls").split()[-1])
        expected_period = f"2025-{expected_month:02d}"
        if source["period"] != expected_period:
            raise TrialBalancePackageError(
                f"{item.filename}: source period {source['period']} does not match "
                "its package month"
            )
        if source["period"] in seen_periods:
            raise TrialBalancePackageError(f"Duplicate source period {source['period']}")
        seen_periods.add(source["period"])
        scope = ExactScope(
            tenant_id=principal.scope.tenant_id,
            legal_entity_id=principal.scope.legal_entity_id,
            period=source["period"],
            currency=principal.scope.currency,
        )
        ingest_request = IngestRequest(
            scope=scope,
            filename=item.filename,
            xls_base64=item.xls_base64,
            source_use="HISTORICAL_REFERENCE",
        )
        prepared.append((item.filename, content, source, compile_source(ingest_request)))

    _report = build_package_report(
        [
            (filename, content, source, receipt.receipt_id)
            for filename, content, source, receipt in prepared
        ],
        currency=principal.scope.currency,
        active_runtime_period=principal.scope.period,
        tenant_id=str(principal.scope.tenant_id),
        legal_entity_id=principal.scope.legal_entity_id,
    )
    # Retention is intentionally imported lazily so pure package validation is
    # usable without a database in tests and tooling.
    from finai_api.storage import retain

    retained: list[tuple[str, bytes, dict[str, Any], str | None]] = []
    for filename, content, source, receipt in prepared:
        scope = ExactScope(
            tenant_id=principal.scope.tenant_id,
            legal_entity_id=principal.scope.legal_entity_id,
            period=source["period"],
            currency=principal.scope.currency,
        )
        request_for_storage = IngestRequest(
            scope=scope,
            filename=filename,
            xls_base64=base64.b64encode(content).decode("ascii"),
            source_use="HISTORICAL_REFERENCE",
        )
        retained_receipt = retain(request_for_storage, receipt, principal.actor_id)
        retained.append((filename, content, source, retained_receipt.receipt_id))
    return build_package_report(
        retained,
        currency=principal.scope.currency,
        active_runtime_period=principal.scope.period,
        tenant_id=str(principal.scope.tenant_id),
        legal_entity_id=principal.scope.legal_entity_id,
    )

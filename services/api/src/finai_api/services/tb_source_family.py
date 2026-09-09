"""Observed 1C turnover trial-balance family binding.

The family is a source construct.  It carries the heading-derived period and
chart fingerprint for each retained snapshot without asserting a canonical
company, currency, journal, or published financial fact.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from finai_api.services.independent_tb_reader import TBMonth, family_deltas

SOURCE_CLASS = "1C_TURNOVER_TRIAL_BALANCE"
CONTRACT_VERSION = "1c_turnover_trial_balance@v1"


@dataclass(frozen=True, slots=True)
class SourcePeriodSnapshot:
    snapshot_id: str
    receipt_id: str | None
    filename: str
    source_sha256: str
    observed_period: str
    period_start: str
    period_end: str
    sheet: str
    company_heading: str
    construction_state: str
    evidence_class: str
    control_row: int
    row_count: int
    root_count: int
    chart_fingerprint: str
    working_period: str | None
    findings: tuple[str, ...]
    # Bi-temporal source coordinates.  ``valid_at`` is the source heading's
    # period end; ``known_at`` is the immutable intake timestamp.  Keeping
    # these on each snapshot prevents consumers from silently substituting a
    # credential/session date for business time.
    valid_at: str
    known_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "receipt_id": self.receipt_id,
            "filename": self.filename,
            "source_sha256": self.source_sha256,
            "observed_period": self.observed_period,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "sheet": self.sheet,
            "company_heading": self.company_heading,
            "construction_state": self.construction_state,
            "evidence_class": self.evidence_class,
            "control_row": self.control_row,
            "row_count": self.row_count,
            "root_count": self.root_count,
            "chart_fingerprint": self.chart_fingerprint,
            "working_period": self.working_period,
            "findings": list(self.findings),
            "valid_at": self.valid_at,
            "known_at": self.known_at,
        }


@dataclass(frozen=True, slots=True)
class SourceFamily:
    family_id: str
    family_key: str
    contract_version: str
    source_class: str
    legal_entity_candidate: str
    chart_fingerprint: str
    snapshots: tuple[SourcePeriodSnapshot, ...]
    status: str = "OBSERVED_REVIEW_REQUIRED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "family_key": self.family_key,
            "contract_version": self.contract_version,
            "source_class": self.source_class,
            "legal_entity_candidate": self.legal_entity_candidate,
            "chart_fingerprint": self.chart_fingerprint,
            "snapshots": [snapshot.as_dict() for snapshot in self.snapshots],
            "status": self.status,
        }


def family_reuse_report(months: Sequence[TBMonth]) -> dict[str, Any]:
    """Describe pack reuse and review-only deltas across a recurring family."""

    ordered = tuple(sorted(months, key=lambda item: item.period))
    if not ordered:
        raise ValueError("At least one observed TB snapshot is required")
    deltas = family_deltas(ordered)
    return {
        "contract": "source-family-reuse/1",
        "pack_applied_once": True,
        "baseline_period": ordered[0].period,
        "classification_reused_for": [month.period for month in ordered[1:]],
        "review_required_periods": [
            delta.to_period for delta in deltas if delta.requires_review
        ],
        "deltas": [
            {
                "from_period": delta.from_period,
                "to_period": delta.to_period,
                "new_account_codes": list(delta.new_account_codes),
                "removed_account_codes": list(delta.removed_account_codes),
                "new_outline_levels": list(delta.new_outline_levels),
                "removed_outline_levels": list(delta.removed_outline_levels),
                "outline_shape_changed": delta.outline_shape_changed,
                "measure_columns_changed": delta.measure_columns_changed,
                "heading_language_changed": delta.heading_language_changed,
                "classification_reuse": delta.auto_reuse_existing_classification,
                "review_required": delta.requires_review,
            }
            for delta in deltas
        ],
    }


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def bind_source_family(
    months: Sequence[TBMonth],
    *,
    receipt_ids: Sequence[str | None] | None = None,
    working_period: str | None = None,
    known_at_by_receipt: Mapping[str, str | None] | None = None,
) -> SourceFamily:
    """Bind ordered observed snapshots into one recurring source family.

    Periods are parsed from each workbook heading by the independent reader;
    ``working_period`` is retained only as a finding when it differs.  No
    credential period is used to rewrite an observed period.
    """

    ordered = tuple(sorted(months, key=lambda item: item.period))
    if not ordered:
        raise ValueError("At least one observed TB snapshot is required")
    if len({month.period for month in ordered}) != len(ordered):
        raise ValueError("A source family cannot contain duplicate observed periods")
    ids = tuple(receipt_ids or ())
    if ids and len(ids) != len(ordered):
        raise ValueError("receipt_ids must align with the ordered observed snapshots")
    if not ids:
        ids = (None,) * len(ordered)
    headings = {month.company_heading.strip() for month in ordered}
    if len(headings) != 1:
        raise ValueError("Source family headings changed; review the legal-entity delta")
    # A fingerprint change is a reviewable family drift, not a new hardcoded
    # company branch.  Keep the first fingerprint as the family identity and
    # expose later deltas in each snapshot's findings.
    family_fingerprint = ordered[0].fingerprint.digest
    family_key = _digest(
        {
            "contract": CONTRACT_VERSION,
            "source_class": SOURCE_CLASS,
            "company_heading": ordered[0].company_heading.strip(),
            "chart_fingerprint": family_fingerprint,
        }
    )
    family_id = "sf_" + family_key
    snapshots: list[SourcePeriodSnapshot] = []
    for index, month in enumerate(ordered):
        findings: list[str] = []
        if working_period and month.period != working_period:
            findings.append(
                f"OBSERVED_PERIOD_DIFFERS_FROM_WORKING_SCOPE:{working_period}"
            )
        if month.fingerprint.digest != family_fingerprint:
            findings.append("SOURCE_FAMILY_SCHEMA_DRIFT_REVIEW_REQUIRED")
        snapshot_key = _digest(
            {
                "family_id": family_id,
                "period": month.period,
                "source_sha256": month.source_sha256,
            }
        )
        receipt_id = ids[index]
        snapshots.append(
            SourcePeriodSnapshot(
                snapshot_id="sps_" + snapshot_key,
                receipt_id=receipt_id,
                filename=month.filename,
                source_sha256=month.source_sha256,
                observed_period=month.period,
                period_start=month.period_start.isoformat(),
                period_end=month.period_end.isoformat(),
                sheet=month.sheet,
                company_heading=month.company_heading,
                construction_state="OBSERVED",
                evidence_class="SOURCE_BOUND",
                control_row=month.control.source_row,
                row_count=month.nonblank_row_count,
                root_count=len(month.root_rows),
                chart_fingerprint=month.fingerprint.digest,
                working_period=working_period,
                findings=tuple(findings),
                valid_at=month.period_end.isoformat(),
                known_at=(
                    known_at_by_receipt.get(receipt_id)
                    if known_at_by_receipt and receipt_id is not None
                    else None
                ),
            )
        )
    return SourceFamily(
        family_id=family_id,
        family_key="source-family:" + family_key,
        contract_version=CONTRACT_VERSION,
        source_class=SOURCE_CLASS,
        legal_entity_candidate=ordered[0].company_heading,
        chart_fingerprint=family_fingerprint,
        snapshots=tuple(snapshots),
    )

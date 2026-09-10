"""Independent Decimal reader proof against the binding SGP 2025 controls."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from finai_api.services.independent_tb_reader import (
    TBAuditExpectation,
    TBControlMismatch,
    continuity_breaks,
    family_deltas,
    mark_overlaps,
    read_audit_fixture,
)

EXPECTED = {
    1: (2912, 33, "453974719.53", "511929505.16", "481653693.79", 2917),
    2: (2951, 33, "481670361.67", "529353044.21", "516857773.88", 2956),
    3: (3101, 33, "512119387.75", "386324334.74", "531707610.86", 3106),
    4: (3056, 33, "529869670.03", "549386091.95", "534637509.11", 3061),
    5: (3126, 34, "534637625.87", "482739137.06", "555868698.53", 3131),
    6: (3294, 34, "556035372.27", "548423357.54", "557305161.90", 3299),
    7: (3283, 33, "557297798.23", "749795757.17", "561034569.01", 3288),
    8: (3193, 33, "561034547.02", "746422914.81", "563509486.17", 3198),
    9: (3386, 34, "562987188.09", "807658317.03", "597291834.68", 3391),
    10: (3308, 36, "455744466.09", "1006567423.42", "460199164.54", 3313),
    11: (3236, 36, "459949738.70", "721513449.05", "480297003.74", 3241),
    12: (3291, 36, "480149772.71", "895182636.95", "502654668.80", 3296),
}


def _control_manifest() -> dict:
    path = Path(__file__).parent / "fixtures" / "sgp-2025-control-table.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["contract"] == "tb-audit-control/1"
    assert value["fixture_id"] == "SGP-2025"
    assert len(value["months"]) == 12
    return value


def _fixture_dir() -> Path:
    return Path(
        os.environ.get(
            "FINAI_SGP_TB_FIXTURE_DIR",
            os.environ.get("FINAI_PETROLEUM_FIXTURES", r"D:\download c\TB"),
        )
    )


def _expectations() -> dict[str, TBAuditExpectation]:
    manifest = _control_manifest()
    committed = {item["month"]: item for item in manifest["months"]}
    assert set(committed) == set(EXPECTED)
    return {
        item["period"]: TBAuditExpectation(
            filename=item["filename"],
            period=item["period"],
            nonblank_rows=item["nonblank_rows"],
            root_rows=item["root_rows"],
            opening=Decimal(item["opening"]),
            turnover=Decimal(item["turnover"]),
            closing=Decimal(item["closing"]),
            control_row=item["control_row"],
        )
        for item in manifest["months"]
    }


def test_committed_sgp_control_manifest_is_complete_and_deterministic():
    manifest = _control_manifest()
    periods = [item["period"] for item in manifest["months"]]
    assert periods == [f"2025-{month:02d}" for month in range(1, 13)]
    assert len({item["filename"] for item in manifest["months"]}) == 12
    assert manifest["total_turnover"] == "7935295969.09"


@pytest.fixture(scope="module")
def authentic_months():
    root = _fixture_dir()
    paths = [root / f"SGP {month}.xls" for month in range(1, 13)]
    if not all(path.is_file() for path in paths):
        pytest.skip(f"SGP fixture directory is not configured: {root}")
    proofs = read_audit_fixture(paths, _expectations())
    return tuple(proof.month for proof in proofs)


def test_all_twelve_authentic_months_match_frozen_audit_controls(authentic_months):
    assert len(authentic_months) == 12
    assert [month.period for month in authentic_months] == [
        f"2025-{month:02d}" for month in range(1, 13)
    ]
    assert all(
        len(month.root_rows) == EXPECTED[index][1]
        for index, month in enumerate(authentic_months, 1)
    )
    assert sum(
        (month.control.amounts["turnover_debit"] for month in authentic_months), Decimal(0)
    ) == Decimal("7935295969.09")
    assert all(
        isinstance(value, Decimal)
        for month in authentic_months
        for row in month.rows
        for value in row.amounts.values()
        if value is not None
    )


def test_january_7410_overlap_preserves_root_and_points_to_survivor(authentic_months):
    month = mark_overlaps(authentic_months[0])
    rows = {row.source_row: row for row in month.rows}
    assert rows[2832].additive_ok is True
    assert rows[2832].duplicate_of is None
    for source_row in (2833, 2834, 2860, 2862):
        assert rows[source_row].additive_ok is False
        assert rows[source_row].duplicate_of == 2832
        assert rows[source_row].overlap_reason == "OVERLAPPING_SOURCE_HIERARCHY"
    assert rows[2832].amounts["turnover_debit"] == Decimal("2587329.2")


def test_january_golden_statement_samples_keep_account_period_semantics(authentic_months):
    month = authentic_months[0]

    def account_rows(code: str):
        return [row for row in month.rows if row.account_code == code]

    assert any(
        row.amounts["turnover_credit"] == Decimal("48832047.44")
        for row in account_rows("6110")
    )
    assert any(
        row.amounts["turnover_debit"] == Decimal("37685779.61")
        for row in account_rows("7110")
    )
    assert any(
        row.amounts["closing_debit"] == Decimal("36177397.80")
        for row in account_rows("1610")
    )
    assert any(
        row.amounts["closing_debit"] == Decimal("17212372.96")
        for row in account_rows("141X")
    )


def test_family_deltas_reuse_layout_and_surface_account_outline_drift(authentic_months):
    deltas = family_deltas(authentic_months)
    assert len(deltas) == 11
    assert all(delta.requires_review for delta in deltas)
    assert all(delta.auto_reuse_existing_classification for delta in deltas)
    assert any("6120" in delta.new_account_codes for delta in deltas)
    assert any(delta.outline_shape_changed for delta in deltas)


def test_continuity_exposes_one_control_break_for_each_boundary(authentic_months):
    breaks = continuity_breaks(authentic_months)
    controls = [item for item in breaks if item.scope == "CONTROL"]
    assert len(controls) == 11
    september_october = next(
        item
        for item in controls
        if item.period_from == "2025-09" and item.period_to == "2025-10"
    )
    assert september_october.delta == Decimal("-141547368.59")
    assert september_october.materiality == "MATERIAL"
    assert any(item.scope == "ROOT" for item in breaks)
    assert any(item.scope == "ACCOUNT" for item in breaks)


def test_audit_reader_fails_closed_on_a_control_mismatch(authentic_months):
    month = authentic_months[0]
    expected = replace(_expectations()[month.period], turnover=Decimal("0"))
    with pytest.raises(TBControlMismatch, match="2025-01"):
        # ``verify_control`` is intentionally reached through the same API as
        # the fixture; the mismatch must not be normalized or repaired.
        from finai_api.services.independent_tb_reader import verify_control

        verify_control(month, expected)

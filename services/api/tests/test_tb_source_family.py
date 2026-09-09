"""Observed-period binding remains independent of the credential period."""

from pathlib import Path

import pytest

from finai_api.services.independent_tb_reader import read_tb_path
from finai_api.services.tb_source_family import bind_source_family, family_reuse_report


@pytest.fixture(scope="module")
def family():
    root = Path(r"D:\download c\TB")
    paths = [root / f"SGP {month}.xls" for month in range(1, 13)]
    if not all(path.is_file() for path in paths):
        pytest.skip("private SGP fixture directory is not available")
    months = tuple(read_tb_path(path) for path in paths)
    return bind_source_family(
        months,
        receipt_ids=[f"receipt-{index}" for index in range(12)],
        working_period="2026-08",
    )


def test_family_uses_heading_period_and_retains_all_snapshots(family):
    assert family.source_class == "1C_TURNOVER_TRIAL_BALANCE"
    assert family.contract_version == "1c_turnover_trial_balance@v1"
    assert [snapshot.observed_period for snapshot in family.snapshots] == [
        f"2025-{month:02d}" for month in range(1, 13)
    ]
    assert all(snapshot.construction_state == "OBSERVED" for snapshot in family.snapshots)
    assert all(snapshot.evidence_class == "SOURCE_BOUND" for snapshot in family.snapshots)
    assert all(
        "OBSERVED_PERIOD_DIFFERS_FROM_WORKING_SCOPE:2026-08" in snapshot.findings
        for snapshot in family.snapshots
    )


def test_family_identity_is_deterministic(family):
    assert family.family_id.startswith("sf_")
    assert family.family_key == "source-family:" + family.family_id.removeprefix("sf_")
    assert len({snapshot.snapshot_id for snapshot in family.snapshots}) == 12


def test_reuse_applies_the_pack_once_and_surfaces_review_deltas(family):
    root = Path(r"D:\download c\TB")
    months = tuple(read_tb_path(root / f"SGP {month}.xls") for month in range(1, 13))
    report = family_reuse_report(months)
    assert report["pack_applied_once"] is True
    assert report["baseline_period"] == "2025-01"
    assert report["classification_reused_for"][-2:] == ["2025-11", "2025-12"]
    assert "2025-09" in report["review_required_periods"]
    assert "2025-10" in report["review_required_periods"]
    sep_oct = next(item for item in report["deltas"] if item["to_period"] == "2025-10")
    assert sep_oct["classification_reuse"] is True
    assert sep_oct["review_required"] is True

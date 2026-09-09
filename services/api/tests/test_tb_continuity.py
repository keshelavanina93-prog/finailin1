from pathlib import Path

import pytest

from finai_api.services.independent_tb_reader import read_tb_path
from finai_api.services.tb_continuity import continuity_report


@pytest.fixture(scope="module")
def months():
    root = Path(r"D:\download c\TB")
    paths = [root / f"SGP {month}.xls" for month in range(1, 13)]
    if not all(path.is_file() for path in paths):
        pytest.skip("private SGP fixture directory is not available")
    return tuple(read_tb_path(path) for path in paths)


def test_all_eleven_boundaries_remain_visible(months):
    report = continuity_report(months)
    assert report["status"] == "BREAKS_OPEN"
    assert report["year_view"] == "TWELVE_FILES_RETAINED_WITH_BREAKS"
    assert report["boundaries_expected"] == 11
    assert report["boundaries_observed"] == 11
    september_october = next(
        item
        for item in report["breaks"]
        if item["period_from"] == "2025-09"
        and item["period_to"] == "2025-10"
        and item["scope"] == "CONTROL"
    )
    assert september_october["delta"] == "-141547368.59"
    assert report["material_break_count"] > 0


def test_single_snapshot_does_not_claim_continuity(months):
    report = continuity_report(months[:1])
    assert report["status"] == "INSUFFICIENT_PERIODS"
    assert report["year_view"] == "FEWER_THAN_TWO_FILES"

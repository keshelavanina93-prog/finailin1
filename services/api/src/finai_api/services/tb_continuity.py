"""Generic adjacent-period continuity for retained trial-balance snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Any

from finai_api.services.independent_tb_reader import TBMonth, continuity_breaks


def continuity_report(
    months: Sequence[TBMonth], *, materiality_threshold: Decimal = Decimal("0.01")
) -> dict[str, Any]:
    """Return all adjacent boundaries without claiming annual continuity."""

    ordered = tuple(sorted(months, key=lambda item: item.period))
    if len(ordered) < 2:
        return {
            "contract": "tb-continuity/1",
            "status": "INSUFFICIENT_PERIODS",
            "year_view": "FEWER_THAN_TWO_FILES",
            "boundaries_expected": 0,
            "boundaries_observed": 0,
            "breaks": [],
        }
    breaks = continuity_breaks(ordered, materiality_threshold=materiality_threshold)
    boundary_pairs = [
        (previous.period, current.period)
        for previous, current in pairwise(ordered)
    ]
    observed_pairs = sorted({(item.period_from, item.period_to) for item in breaks})
    return {
        "contract": "tb-continuity/1",
        "status": "BREAKS_OPEN" if breaks else "CONTINUOUS_REVIEWED",
        "year_view": (
            "TWELVE_FILES_RETAINED_WITH_BREAKS"
            if len(ordered) == 12 and breaks
            else "ANNUAL_CONTINUOUS"
            if len(ordered) == 12
            else "PARTIAL_PERIOD_SET"
        ),
        "boundaries_expected": len(boundary_pairs),
        "boundaries_observed": len(observed_pairs),
        "boundary_pairs": [list(pair) for pair in boundary_pairs],
        "breaks": [item.as_dict() for item in breaks],
        "material_break_count": sum(item.materiality == "MATERIAL" for item in breaks),
    }

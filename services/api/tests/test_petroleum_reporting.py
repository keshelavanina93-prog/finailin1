import os
from decimal import Decimal
from pathlib import Path

import pytest

from finai_api.services.petroleum_reporting import classify, reconstruct


def test_explicit_product_exceptions_and_legacy_difference() -> None:
    assert classify("Natural Gas (Wholesale), m3", "revenue") == "retail.cng"
    assert classify("Euro Regular (Wholesale)", "cogs") == "wholesale.petrol"
    assert classify("Premium (Wholesale)", "cogs") == "other"
    assert classify("Kerosene, L", "revenue") == "other"


def test_authentic_reference_recomputes_shared_formulas_and_preserves_conflicts() -> None:
    path = os.environ.get("FINAI_OPERATING_REPORT_FIXTURE")
    if not path:
        pytest.skip("Authentic workbook path not supplied")
    result = reconstruct(Path(path).read_bytes())
    metrics = {item["id"]: item for item in result["metrics"]}
    assert abs(Decimal(metrics["revenue.total"]["amount"]) - Decimal("111474234.29")) < Decimal(
        "0.01"
    )
    assert abs(
        Decimal(metrics["revenue.including_other"]["amount"]) - Decimal("113136012.18")
    ) < Decimal("0.01")
    assert abs(
        Decimal(metrics["cogs.including_other"]["amount"]) - Decimal("101982177.43")
    ) < Decimal("0.01")
    comparison = next(c for c in result["comparisons"] if c["metric"] == "cogs.total")
    assert abs(Decimal(comparison["difference"]) + Decimal("416044.93")) < Decimal("0.01")
    assert metrics["legacy_ebitda"]["amount"] is None
    assert result["state"] == "REFERENCE_ONLY"
    assert not result["findings"]
    assert not any(
        f["source_row"] == 27 for f in result["facts"] if f["source_sheet"] == "COGS Breakdown"
    )
    assert result == reconstruct(Path(path).read_bytes())

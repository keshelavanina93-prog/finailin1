from decimal import ROUND_UP, Inexact, Rounded, localcontext

import pytest

from finai_api.services.journal_amount_classification import classify


@pytest.mark.parametrize(
    "literal,categories,eligible",
    [
        ("731.97", [], True),
        ("-9.10", ["SIGNED_CORRECTION"], False),
        ("0", ["ZERO"], False),
        ("1.2345678", ["SCALE_GREATER_THAN_SIX"], False),
        ("12.340000000000001", ["SCALE_GREATER_THAN_SIX", "SOURCE_NUMERIC_TAIL"], False),
        ("NaN", ["OTHER"], False),
    ],
)
def test_lossless_amount_classification(literal, categories, eligible):
    result = classify(literal)
    assert result["literal"] == literal and result["categories"] == categories
    assert result["journal_amount_compatible"] is eligible
    assert result["conversion"] == "NONE" and not result["rounding_authorized"]


@pytest.mark.parametrize("literal", ["12.340000000000001", "731.97", "0", "-9.10", "1.2345678"])
def test_amount_disposition_is_independent_of_callers_decimal_settings(literal):
    expected = classify(literal)
    with localcontext() as caller:
        caller.prec = 2
        caller.Emax = 2
        caller.Emin = -2
        caller.rounding = ROUND_UP
        caller.traps[Inexact] = caller.traps[Rounded] = True
        assert classify(literal) == expected
        assert caller.prec == 2 and caller.Emax == 2 and caller.rounding == ROUND_UP

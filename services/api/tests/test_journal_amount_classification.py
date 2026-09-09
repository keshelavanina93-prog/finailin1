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

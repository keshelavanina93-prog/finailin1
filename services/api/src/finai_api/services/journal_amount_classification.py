"""Lossless classification; numeric tails are observations, never rounding authority."""

from decimal import Decimal, InvalidOperation

from finai_api.domain.journal_balance import balanced_amounts


def classify(literal):
    categories = []
    try:
        amount = Decimal(literal)
        if not amount.is_finite():
            raise InvalidOperation
        exponent = amount.as_tuple().exponent
        assert isinstance(exponent, int)
        scale = max(0, -exponent)
        if amount < 0:
            categories.append("SIGNED_CORRECTION")
        if amount == 0:
            categories.append("ZERO")
        if scale > 6:
            categories.append("SCALE_GREATER_THAN_SIX")
            # Only describes a small residual near two-decimal representation.
            # It does not infer its cause or authorize changing the amount.
            residual = abs(amount - amount.quantize(Decimal("0.01")))
            if residual and residual < Decimal("0.000001"):
                categories.append("SOURCE_NUMERIC_TAIL")
        balanced_amounts(
            [{"side": side, "amount": {"amount": literal}} for side in ("DEBIT", "CREDIT")]
        )
        eligible = True
    except (InvalidOperation, ValueError, TypeError):
        eligible = False
        if not categories:
            categories.append("OTHER")
    return {
        "literal": literal,
        "categories": categories,
        "journal_amount_compatible": eligible,
        "conversion": "NONE",
        "rounding_authorized": False,
    }

from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")


def money(value):
    """Quantise any number-like to 2 decimal places (ROUND_HALF_UP). None -> 0.00."""
    if value is None or value == "":
        return ZERO
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

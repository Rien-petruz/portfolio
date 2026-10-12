"""Exact fixed-point arithmetic for exchange prices and quantities.

Binance spot publishes prices and quantities as decimal strings with at most
8 fractional digits. We parse them *exactly* into integers scaled by 10**8
("e8" units). Integer arithmetic is exact, hashable, cheap to compare and
avoids binary floating-point rounding when checking tick/step filters.

Floats are used only for statistical features (returns, volatility), never
for precision-sensitive checks.
"""

from __future__ import annotations

import re
from decimal import Decimal

SCALE = 8
ONE = 10**SCALE
_POW10 = tuple(10**i for i in range(SCALE + 1))
_NUM_RE = re.compile(r"-?[0-9]+(?:\.[0-9]*)?")


class PrecisionError(ValueError):
    """Raised when a decimal string cannot be represented exactly at SCALE."""


def parse_e8(s: str) -> int:
    """Parse a decimal string such as ``"25.35190000"`` into e8 units exactly.

    Raises ``ValueError`` for malformed input and ``PrecisionError`` when the
    value has non-zero digits beyond 8 decimal places (it would be silently
    rounded otherwise).
    """
    # Fast path: Binance's canonical format, e.g. "25.35190000" (ASCII digits,
    # exactly 8 decimals). One int() call on the concatenated digits.
    i, dot, f = s.partition(".")
    if s.isascii() and i.isdigit():
        n = len(f)
        if dot:
            if n == SCALE and f.isdigit():
                return int(i + f)
            if 0 < n < SCALE and f.isdigit():
                return int(i + f) * _POW10[SCALE - n]
        else:
            return int(i) * ONE
    if _NUM_RE.fullmatch(s) is None:
        raise ValueError(f"not a decimal number: {s!r}")
    neg = s[0] == "-"
    if neg:
        s = s[1:]
    dot = s.find(".")
    if dot < 0:
        v = int(s) * ONE
    else:
        frac = s[dot + 1 :]
        n = len(frac)
        if n > SCALE:
            if frac[SCALE:].strip("0"):
                raise PrecisionError(f"more than {SCALE} significant decimals: {s!r}")
            frac = frac[:SCALE]
            n = SCALE
        v = int(s[:dot]) * ONE + (int(frac) * _POW10[SCALE - n] if n else 0)
    return -v if neg else v


def e8_to_decimal(v: int) -> Decimal:
    return Decimal(v).scaleb(-SCALE)


def e8_to_str(v: int) -> str:
    sign = "-" if v < 0 else ""
    q, r = divmod(abs(v), ONE)
    return f"{sign}{q}.{r:08d}"


def e8_to_float(v: int) -> float:
    return v / ONE


def mul_e8(a: int, b: int) -> int:
    """Product of two e8 values in e8 units, truncated toward zero."""
    p = a * b
    return p // ONE if p >= 0 else -((-p) // ONE)


def floor_to_step(v: int, step: int) -> int:
    if step <= 0:
        return v
    return (v // step) * step


def ceil_to_step(v: int, step: int) -> int:
    if step <= 0:
        return v
    return -((-v) // step) * step

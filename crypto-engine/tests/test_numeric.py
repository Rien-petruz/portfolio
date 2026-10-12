from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from marketintel.numeric import (ONE, PrecisionError, ceil_to_step, e8_to_decimal, e8_to_str,
                                 floor_to_step, mul_e8, parse_e8)


@pytest.mark.parametrize("s,expected", [
    ("25.35190000", 2_535_190_000),
    ("0.00000001", 1),
    ("1", ONE),
    ("0", 0),
    ("0.0", 0),
    ("100.", 100 * ONE),
    ("-1.5", -150_000_000),
    ("60000.12345678", 6_000_012_345_678),
    ("1.000000000000", ONE),  # extra zeros beyond 8 decimals are exact
])
def test_parse_e8_exact(s, expected):
    assert parse_e8(s) == expected


@pytest.mark.parametrize("s", ["", "abc", "1e5", " 1", "1 ", "1_000", "--1", ".5", "1.2.3", "+1", "NaN", "inf"])
def test_parse_e8_rejects_malformed(s):
    with pytest.raises(ValueError):
        parse_e8(s)


def test_parse_e8_rejects_lossy_precision():
    with pytest.raises(PrecisionError):
        parse_e8("0.000000001")
    with pytest.raises(PrecisionError):
        parse_e8("1.123456789")


@given(st.decimals(min_value=Decimal("-1e12"), max_value=Decimal("1e12"), places=8,
                   allow_nan=False, allow_infinity=False))
def test_parse_matches_decimal(d):
    s = format(d, "f")
    assert parse_e8(s) == int(d * ONE)
    assert e8_to_decimal(parse_e8(s)) == d
    assert parse_e8(e8_to_str(parse_e8(s))) == parse_e8(s)


def test_steps_and_mul():
    assert floor_to_step(1234, 100) == 1200
    assert ceil_to_step(1234, 100) == 1300
    assert ceil_to_step(1200, 100) == 1200
    assert floor_to_step(-1234, 100) == -1300
    assert floor_to_step(77, 0) == 77
    assert mul_e8(parse_e8("1.5"), parse_e8("2.5")) == parse_e8("3.75")
    assert mul_e8(parse_e8("-1.5"), parse_e8("0.00000001")) == -1  # truncates toward zero

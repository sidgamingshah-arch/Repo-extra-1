from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.ontology import NumberFormat
from app.services.numbers import parse_number


def test_us_format():
    p = parse_number("1,234.56")
    assert p.ok and p.value == Decimal("1234.56")


def test_parentheses_negative():
    p = parse_number("(1,204)")
    assert p.ok and p.value == Decimal("-1204") and p.is_negative_paren


def test_eu_format():
    fmt = NumberFormat(decimal=",", thousands=".")
    p = parse_number("1.234,56", fmt)
    assert p.ok and p.value == Decimal("1234.56")


def test_indian_grouping():
    p = parse_number("1,23,456")
    assert p.ok and p.value == Decimal("123456")


def test_unicode_minus_and_currency_symbol():
    p = parse_number("−500")
    assert p.ok and p.value == Decimal("-500")
    p2 = parse_number("₹ 2,000")
    assert p2.ok and p2.value == Decimal("2000")


def test_non_numeric():
    assert not parse_number("n/a").ok
    assert not parse_number("").ok

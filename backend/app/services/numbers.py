"""Locale-aware number parsing + sign detection.

Decimal / thousands separators and grouping differ by locale (``1.234,56`` EU ·
``1,234.56`` US · Indian lakh grouping ``1,23,456``). Getting this wrong silently
corrupts values, so parsing is driven by the ontology's per-locale ``NumberFormat``.
Also detects the printed sign (parentheses / trailing minus / unicode minus) — the
first, cheapest tier of the sign-detection stage.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.schemas.ontology import NumberFormat

_PAREN = re.compile(r"^\((.*)\)$")
_TRAILING_MINUS = re.compile(r"^(.*)-$")
_NON_NUMERIC = re.compile(r"[^0-9.,\-−–()]")


class ParsedNumber:
    __slots__ = ("value_raw", "value", "is_negative_paren", "ok")

    def __init__(self, value_raw: Decimal | None, value: Decimal | None,
                 is_negative_paren: bool, ok: bool):
        self.value_raw = value_raw
        self.value = value
        self.is_negative_paren = is_negative_paren
        self.ok = ok


def parse_number(text: str, fmt: NumberFormat | None = None) -> ParsedNumber:
    """Parse a printed cell string into a signed Decimal per the locale format.

    ``value_raw`` is the parsed magnitude with the *printed* sign applied (including
    parentheses-as-negative). Sign *normalization* against the ontology convention
    happens later in the normalize stage; here we only decode what the page shows.
    """
    fmt = fmt or NumberFormat()
    if text is None:
        return ParsedNumber(None, None, False, False)

    s = text.strip()
    if not s:
        return ParsedNumber(None, None, False, False)

    negative = False
    is_paren = False

    # Unicode minus / en-dash → ascii minus.
    s = s.replace("−", "-").replace("–", "-")

    m = _PAREN.match(s)
    if m and "paren" in fmt.negative:
        negative = True
        is_paren = True
        s = m.group(1).strip()

    tm = _TRAILING_MINUS.match(s)
    if tm:
        negative = True
        s = tm.group(1).strip()

    if s.startswith("-"):
        negative = True
        s = s[1:].strip()

    # Strip currency symbols / stray letters but keep separators.
    s = _NON_NUMERIC.sub("", s).strip()
    if not s:
        return ParsedNumber(None, None, False, False)

    # Remove thousands separators, normalise decimal to '.'.
    if fmt.thousands:
        s = s.replace(fmt.thousands, "")
    if fmt.decimal and fmt.decimal != ".":
        s = s.replace(fmt.decimal, ".")

    try:
        magnitude = Decimal(s)
    except InvalidOperation:
        return ParsedNumber(None, None, False, False)

    signed = -magnitude if negative else magnitude
    return ParsedNumber(value_raw=signed, value=signed,
                        is_negative_paren=is_paren, ok=True)

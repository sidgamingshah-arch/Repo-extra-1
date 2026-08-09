"""Locale-aware number parsing in the extract path (Req 12): EU decimal-comma and Indian
grouping parse when a locale NumberFormat is supplied; the US default is unchanged."""
from __future__ import annotations

from app.core.models.enums import Basis
from app.core.models.geometry import BBox
from app.schemas.ontology import NumberFormat
from app.services.row_reconstruct import Word, build_line_items


def _row(label_x, label, val_text, y=0.2):
    return [
        Word(text=label, bbox=BBox(x0=0.05, y0=y, x1=label_x, y1=y + 0.02)),
        Word(text=val_text, bbox=BBox(x0=0.80, y0=y, x1=0.92, y1=y + 0.02)),
    ]


def test_eu_decimal_comma_parses_with_locale_format():
    eu = NumberFormat(decimal=",", thousands=".")
    words = _row(0.3, "Umsatzerlöse", "1.234.567,89")
    items, _ = build_line_items(words, page_index=0, document_id="h", source_kind="native",
                                number_format=eu)
    ev = next(iter(items[0].values.values()))
    assert float(ev.value) == 1234567.89

    # Without the locale format (US default), that token isn't a valid number → dropped.
    items_us, _ = build_line_items(words, page_index=0, document_id="h", source_kind="native")
    assert not items_us or not items_us[0].values


def test_indian_grouping_parses():
    inr = NumberFormat(decimal=".", thousands=",", grouping="indian")
    words = _row(0.3, "Revenue", "1,23,456")
    items, _ = build_line_items(words, page_index=0, document_id="h", source_kind="native",
                                number_format=inr)
    ev = next(iter(items[0].values.values()))
    assert int(ev.value) == 123456


def test_us_default_unchanged():
    words = _row(0.3, "Trade receivables", "3,410")
    items, _ = build_line_items(words, page_index=0, document_id="h", source_kind="native")
    ev = items[0].get_value(Basis.CONSOLIDATED, period_label="current")
    assert int(ev.value) == 3410

"""Row reconstruction (shared by native-PDF and OCR paths): value/label/note splitting
and the conservative wrapped-label merge."""
from __future__ import annotations

from app.core.models.enums import Basis
from app.core.models.geometry import BBox
from app.services.row_reconstruct import Word, build_line_items


def _w(text: str, x0: float, y0: float, x1: float, y1: float) -> Word:
    return Word(text=text, bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1))


def _build(words: list[Word]):
    items, _ = build_line_items(words, page_index=0, document_id="d1", source_kind="native")
    return items


def test_single_line_row_splits_label_note_and_values():
    items = _build([
        _w("Trade", 0.10, 0.20, 0.16, 0.22),
        _w("receivables", 0.17, 0.20, 0.28, 0.22),
        _w("Note", 0.50, 0.20, 0.55, 0.22),
        _w("15", 0.56, 0.20, 0.58, 0.22),
        _w("3,410", 0.72, 0.20, 0.80, 0.22),
        _w("2,900", 0.86, 0.20, 0.94, 0.22),
    ])
    assert len(items) == 1
    li = items[0]
    assert li.source_label == "Trade receivables"
    assert li.note_number == "15"                                   # note ref, not a value
    cur = li.get_value(Basis.CONSOLIDATED, period_label="current")
    prior = li.get_value(Basis.CONSOLIDATED, period_label="prior")
    assert cur is not None and int(cur.value) == 3410
    assert prior is not None and int(prior.value) == 2900


def test_wrapped_label_is_merged_into_the_valued_line():
    """A label that wraps across two tight, left-aligned lines is stitched back together
    rather than truncated to the fragment on the valued line."""
    items = _build([
        _w("Property,", 0.10, 0.30, 0.18, 0.315),
        _w("plant", 0.19, 0.30, 0.24, 0.315),
        _w("and", 0.25, 0.30, 0.29, 0.315),
        # continuation line, tight spacing (gap << line height), same left edge:
        _w("equipment", 0.10, 0.318, 0.22, 0.333),
        _w("12,500", 0.72, 0.318, 0.82, 0.333),
    ])
    assert len(items) == 1
    li = items[0]
    assert li.source_label == "Property, plant and equipment"
    cur = li.get_value(Basis.CONSOLIDATED, period_label="current")
    assert cur is not None and int(cur.value) == 12500
    # provenance still anchors on the value's own bbox
    assert cur.provenance is not None and cur.provenance.bbox is not None


def test_section_header_is_not_merged_into_next_item():
    """An ALL-CAPS / standalone header line must stay a header, not be folded into the
    first item below it."""
    items = _build([
        _w("NON-CURRENT", 0.10, 0.30, 0.24, 0.315),
        _w("ASSETS", 0.25, 0.30, 0.33, 0.315),
        _w("Goodwill", 0.10, 0.318, 0.20, 0.333),
        _w("8,000", 0.72, 0.318, 0.80, 0.333),
    ])
    assert len(items) == 1
    assert items[0].source_label == "Goodwill"                      # header not swallowed


def test_loosely_spaced_label_line_is_not_merged():
    """A label-only line far above the next valued line (paragraph gap) is a separate
    heading, not a wrapped continuation."""
    items = _build([
        _w("Other", 0.10, 0.20, 0.16, 0.215),
        _w("reserves", 0.17, 0.20, 0.27, 0.215),
        # big vertical gap → different block:
        _w("Retained", 0.10, 0.40, 0.19, 0.415),
        _w("earnings", 0.20, 0.40, 0.29, 0.415),
        _w("5,100", 0.72, 0.40, 0.80, 0.415),
    ])
    assert len(items) == 1
    assert items[0].source_label == "Retained earnings"             # "Other reserves" dropped, not merged

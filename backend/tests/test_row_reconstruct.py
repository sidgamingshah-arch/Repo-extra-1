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


def test_a_second_figure_in_one_column_does_not_replace_the_first():
    """Two figures inside the SAME value column (a footnote-marked repeat, an OCR double read)
    land on one (basis, period) key. ``column_guard`` says facts differing on nothing declared are
    duplicates, so the first printed figure is kept — overwriting means the row reports whichever
    cell the geometry happened to visit last, with nothing in the output to show it happened."""
    logs: list[str] = []
    words = [
        _w("Trade", 0.10, 0.20, 0.16, 0.212), _w("receivables", 0.17, 0.20, 0.28, 0.212),
        _w("3,410", 0.72, 0.20, 0.78, 0.212), _w("3,411", 0.73, 0.20, 0.79, 0.212),
        _w("2,900", 0.86, 0.20, 0.92, 0.212),
        _w("Inventories", 0.10, 0.24, 0.20, 0.252),
        _w("2,000", 0.72, 0.24, 0.78, 0.252), _w("1,800", 0.86, 0.24, 0.92, 0.252),
        _w("Cash", 0.10, 0.28, 0.16, 0.292),
        _w("1,204", 0.72, 0.28, 0.78, 0.292), _w("980", 0.86, 0.28, 0.92, 0.292),
    ]
    items, _ = build_line_items(words, page_index=0, document_id=None, source_kind="native",
                               log=logs.append)
    tr = next(i for i in items if "Trade" in i.source_label)
    cur = tr.get_value(Basis.CONSOLIDATED, period_label="current")
    assert cur is not None and int(cur.value) == 3410
    assert len(tr.values) == 2                                  # not three, and not overwritten
    assert any("duplicate_fact_dropped" in m for m in logs), logs


def test_a_basis_caption_governs_a_contiguous_run_of_columns():
    """A band caption may be printed left-aligned over its first column or centred over the pair,
    so the columns cannot be handed to the NEAREST caption: on a four-column Group | Company page
    the Group's comparative is a hair nearer the Company caption, and last year's Group figures
    are then read as the Company's current year."""
    from app.core.models.enums import Basis as B
    from app.services.row_reconstruct import _basis_of_columns

    # "Group" printed over the first column, "Company" over the third — the HKEX house style.
    bands = [(B.CONSOLIDATED, 0.527), (B.STANDALONE, 0.782)]
    cols = [0.533, 0.655, 0.781, 0.899]
    assert _basis_of_columns(cols, bands) == {0: B.CONSOLIDATED, 1: B.CONSOLIDATED,
                                             2: B.STANDALONE, 3: B.STANDALONE}
    # …and the same holds when each caption is centred over its own pair.
    assert _basis_of_columns(cols, [(B.CONSOLIDATED, 0.60), (B.STANDALONE, 0.84)]) == {
        0: B.CONSOLIDATED, 1: B.CONSOLIDATED, 2: B.STANDALONE, 3: B.STANDALONE}


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

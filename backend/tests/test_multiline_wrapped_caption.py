"""A note detail whose caption wraps over more than two lines keeps its whole name.

THE DEFECT THIS CLOSES, reported off the notes to a real filing: "full names are not being
extracted". A caption printed as

    Deposits paid for acquisition of
      land use rights in the
      PRC                                    2,500      2,600

was published as "land use rights in the PRC" — a note detail a reader cannot identify and the
mapper cannot place, because its first line was silently dropped.

``_merge_wrapped_labels`` folds a label-only line into the following VALUED row, and its wrap test
required that next row to carry values. That is true of the last continuation line and false of every
earlier one, so on a three-line caption the first line failed the test, was emitted as a label-only
row of its own, and was skipped by the main loop. Two-line captions were unaffected, which is why
this only showed up in the notes — the face rarely wraps a caption three deep, and the notes
routinely do.

``_wrap_reaches_a_value`` looks ahead through consecutive label-only lines instead. The merge is
documented as conservative on purpose, and it stays conservative: the look-ahead is bounded, every
step is still checked for tight spacing and label-column alignment, and a banner or colon sub-heading
stops the chain. ``test_prose_is_not_glued_onto_the_figure_beneath_it`` is the test that holds that
line, because a notes page is mostly prose and an unbounded look-ahead would swallow a paragraph.
"""
from __future__ import annotations

from app.core.models.geometry import BBox
from app.services.notes_extract import extract_note_tables
from app.services.row_reconstruct import Word, build_line_items

LINE_H = 0.011
PER_CHAR = 0.016
# Line spacing for a wrapped caption. It has to sit in a narrow band to exercise the MERGE rather
# than row clustering: above 0.012 so `_group_rows` keeps the printed lines apart (below it they
# cluster into one row and the two lines' words interleave by x, which is a different code path),
# and no more than 0.0176 so the gap stays inside `_tight_below`'s 0.6-line-height window.
STEP = 0.015


def _stack(y0: float, *specs) -> list[list[Word]]:
    """Consecutive printed lines from `y0` down, one STEP apart."""
    return [_line(y0 + i * STEP, text, x0=x0, value=v, value2=v2)
            for i, (text, x0, v, v2) in enumerate(specs)]


def _line(y: float, text: str, *, x0: float = 0.10,
          value: str | None = None, value2: str | None = None) -> list[Word]:
    """One printed line. `x0` above the default models the hanging indent a wrapped caption uses."""
    out, x = [], x0
    for token in text.split():
        width = min(PER_CHAR * len(token), 0.99 - x)
        out.append(Word(text=token, bbox=BBox(x0=x, y0=y, x1=x + width, y1=y + LINE_H)))
        x += width + 0.005
    if value:
        out.append(Word(text=value, bbox=BBox(x0=0.66, y0=y, x1=0.74, y1=y + LINE_H)))
    if value2:
        out.append(Word(text=value2, bbox=BBox(x0=0.84, y0=y, x1=0.92, y1=y + LINE_H)))
    return out


def _note_items(*lines: list[Word]) -> dict[str, list[str]]:
    words = [w for line in lines for w in line]
    tables = extract_note_tables(words, page_index=3, document_id="d1", source_kind="native")
    return {it.raw_label: [str(v.value) for v in it.values.values()]
            for t in tables for it in t.items}


def _face_labels(*lines: list[Word]) -> list[str]:
    words = [w for line in lines for w in line]
    items, _ = build_line_items(words, page_index=0, document_id="d1", source_kind="native")
    return [li.source_label for li in items]


def test_a_three_line_caption_keeps_its_first_line():
    """The reported case. Before the fix the label was "land use rights in the PRC"."""
    got = _note_items(
        _line(0.100, "15. PREPAYMENTS AND OTHER RECEIVABLES"),
        _line(0.140, "Trade receivables", value="1,234", value2="5,678"),
        *_stack(0.180,
                ("Deposits paid for acquisition of", 0.10, None, None),
                ("land use rights in the", 0.13, None, None),
                ("PRC", 0.13, "2,500", "2,600")),
    )
    assert "Deposits paid for acquisition of land use rights in the PRC" in got, (
        f"caption was truncated: {list(got)}")
    assert got["Deposits paid for acquisition of land use rights in the PRC"] == ["2500", "2600"]


def test_a_four_line_caption_keeps_its_first_line():
    """Three continuation lines is the bound, so a four-line caption is the longest that survives
    whole. A caption longer than this is indistinguishable from prose by geometry alone."""
    got = _note_items(
        _line(0.100, "20. OTHER PAYABLES AND ACCRUALS"),
        *_stack(0.150,
                ("Consideration payable for the", 0.10, None, None),
                ("acquisition of a subsidiary", 0.13, None, None),
                ("engaged in property", 0.13, None, None),
                ("development", 0.13, "7,000", "7,100")),
    )
    label = ("Consideration payable for the acquisition of a subsidiary engaged in property "
             "development")
    assert label in got, f"caption was truncated: {list(got)}"
    assert got[label] == ["7000", "7100"]


def test_a_two_line_caption_still_works():
    """The case that already worked — the same code path decides it."""
    got = _note_items(
        _line(0.100, "15. TRADE RECEIVABLES"),
        *_stack(0.150,
                ("Less: allowance for expected", 0.10, None, None),
                ("credit losses", 0.13, "(100)", "(200)")),
    )
    assert "Less: allowance for expected credit losses" in got


def test_a_bilingual_caption_still_merges():
    """A filing that prints the Chinese translation on the next line and the figures beside it."""
    got = _note_items(
        _line(0.100, "15. TRADE RECEIVABLES"),
        *_stack(0.150,
                ("Prepayments and other receivables", 0.10, None, None),
                ("預付款項及其他應收款項", 0.10, "900", "800")),
    )
    assert any("Prepayments and other receivables" in k and "預付款項" in k for k in got), (
        f"the bilingual halves were separated: {list(got)}")


def test_prose_is_not_glued_onto_the_figure_beneath_it():
    """The line the fix must not cross. A notes page is mostly narrative, and the look-ahead is
    bounded precisely so a paragraph cannot be absorbed into the first figure under it. Five
    label-only lines exceed the bound, so the earliest ones stay out of the caption."""
    got = _note_items(
        _line(0.100, "28. CONTINGENT LIABILITIES"),
        *_stack(0.150,
                ("The Group has provided guarantees in respect of", 0.10, None, None),
                ("mortgage facilities granted by certain banks", 0.10, None, None),
                ("to purchasers of the Group's properties. The", 0.10, None, None),
                ("guarantees are released upon the earlier of", 0.10, None, None),
                ("the issue of the property ownership", 0.10, None, None),
                ("certificate", 0.10, "9,000", "8,000")),
    )
    label = next(iter(got))
    assert "The Group has provided guarantees" not in label, (
        f"an entire paragraph was absorbed into one caption: {label!r}")


def test_a_banner_stops_the_chain():
    """A banner introduces what follows; it never continues a caption. Without this the section
    banner would be swallowed into the first item's name and the section lost with it."""
    labels = _face_labels(
        *_stack(0.300,
                ("Current assets", 0.10, None, None),
                ("Amounts due from related", 0.10, None, None),
                ("parties", 0.13, "3,000", None)),
    )
    assert labels == ["Amounts due from related parties"], labels


def test_a_colon_subheading_stops_the_chain():
    """"Adjustments for:" scopes the rows beneath it and is not part of any caption."""
    labels = _face_labels(
        *_stack(0.300,
                ("Adjustments for:", 0.10, None, None),
                ("Depreciation and", 0.10, None, None),
                ("amortisation", 0.13, "450", None)),
    )
    assert labels == ["Depreciation and amortisation"], labels

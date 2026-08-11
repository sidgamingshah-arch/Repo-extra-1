"""Statements that are not two-column comparatives.

Two shapes break the current/prior assumption the rest of the app is built on:

* a statement of CHANGES IN EQUITY, whose columns are equity components (issued capital, each
  reserve, retained profits, non-controlling interests, total equity) and whose rows are
  movements through the year — forcing it into current/prior files a component under a period
  that does not exist;
* a page whose TEXT IS DRAWN SIDEWAYS, which wide statements use to fit a dozen columns — there
  the words advance bottom-to-top, so grouping them into rows by shared y finds no rows at all
  and the page yields nothing.
"""
from __future__ import annotations

from app.core.models.geometry import BBox


def _val(period, value, page=106, x0=0.3):
    return {"basis": "consolidated", "period_label": period, "value": str(value),
            "provenance": {"source_kind": "native", "page_index": page,
                           "bbox": {"x0": x0, "y0": 0.2, "x1": x0 + 0.05, "y1": 0.21}}}


def test_the_equity_statement_is_served_as_a_matrix_with_named_columns():
    from app.api.routes.documents import _build_statement

    rows = [
        {"source_label": "At 1 January 2023", "canonical_key": None, "values": [
            _val("Issued capital", 365064, x0=0.30),
            _val("Retained profits", 12_000, x0=0.55),
            _val("Total equity", 36_625_241, x0=0.80)]},
        {"source_label": "Loss for the year", "canonical_key": None, "values": [
            _val("Retained profits", -8_401_124, x0=0.55),
            _val("Total equity", -8_401_124, x0=0.80)]},
        {"source_label": "At 31 December 2023", "canonical_key": None, "values": [
            _val("Issued capital", 365064, x0=0.30),
            _val("Retained profits", 3_598_876, x0=0.55),
            _val("Total equity", 20_482_326, x0=0.80)]},
    ]
    d = _build_statement(rows, None, "changes_in_equity", "f.pdf")

    assert d["layout"] == "matrix"
    # Columns are the component headers read off the page, ordered as PRINTED (by where the
    # figures sit), not alphabetically and not in dict order.
    assert [c["key"] for c in d["columns"]] == ["Issued capital", "Retained profits",
                                               "Total equity"]
    assert d["periods"] == []                    # a component is not a period

    labels = [r["label"] for r in d["rows"]]
    assert labels == ["At 1 January 2023", "Loss for the year", "At 31 December 2023"]
    closing = d["rows"][-1]
    assert closing["cells"]["Total equity"] == 20_482_326
    assert closing["cells"]["Issued capital"] == 365064
    # An opening/closing balance is the matrix's own subtotal line.
    assert closing["kind"] == "subtotal" and d["rows"][1]["kind"] == "item"
    # v1/v2 stay empty so nothing downstream reads a component as a period.
    assert closing["v1"] is None and closing["v2"] is None
    assert closing["source"] is not None          # still traceable to the page


def test_comparative_rows_never_leak_into_the_matrix():
    """Both shapes coexist in one extraction. A comparative row labels its values positionally
    ("current"/"prior"), a matrix row by column name — that is the discriminator, and without it
    every balance-sheet row appeared in the equity statement and "current" became a column."""
    from app.api.routes.documents import _build_statement

    rows = [
        {"source_label": "Trade receivables", "canonical_key": "bs_current_assets__trade_receivables",
         "values": [_val("current", 198_330, page=103), _val("prior", 466_350, page=103)]},
        {"source_label": "At 1 January 2023", "canonical_key": None, "values": [
            _val("Issued capital", 365064), _val("Total equity", 36_625_241)]},
    ]
    d = _build_statement(rows, None, "changes_in_equity", "f.pdf")
    assert [c["key"] for c in d["columns"]] == ["Issued capital", "Total equity"]
    assert [r["label"] for r in d["rows"]] == ["At 1 January 2023"]


def test_a_single_named_cell_is_not_a_matrix_row():
    """A movement in equity touches at least its own component and a total column, so one named
    cell is chrome — a stray figure, not a row of the statement."""
    from app.api.routes.documents import _build_statement

    rows = [{"source_label": "stray", "canonical_key": None,
             "values": [_val("Total equity", 5)]}]
    assert _build_statement(rows, None, "changes_in_equity", "f.pdf")["rows"] == []


def test_sideways_text_is_read_in_reading_space():
    """A 90°-rotated page: the words advance bottom-to-top, so page-space y is constant along a
    printed row. Read as-is there are no rows; transformed into reading space the row is
    recovered — and provenance keeps the PAGE box so the highlight still lands where the figure
    is drawn."""
    from app.services.pdf_extract import _to_reading_space

    # Two words side by side on a printed row, drawn rotated: they share an x on the page.
    a = BBox(x0=0.20, y0=0.70, x1=0.21, y1=0.80)
    b = BBox(x0=0.20, y0=0.40, x1=0.21, y1=0.50)
    ra, rb = _to_reading_space(a, 90), _to_reading_space(b, 90)
    # In reading space they now share a row (same y band) and differ across it.
    assert abs(ra.y0 - rb.y0) < 1e-9
    assert ra.x0 != rb.x0
    # ...and the transform stays inside the unit square.
    for box in (ra, rb):
        assert 0.0 <= box.x0 <= box.x1 <= 1.0
        assert 0.0 <= box.y0 <= box.y1 <= 1.0


def test_reading_space_is_a_no_op_for_an_upright_page():
    """The overwhelming majority of pages are upright; they must be untouched."""
    from app.services.pdf_extract import _to_reading_space

    box = BBox(x0=0.1, y0=0.2, x1=0.3, y1=0.25)
    assert _to_reading_space(box, 0) is box


def test_a_rotated_word_keeps_its_page_box_for_click_to_source():
    from app.services.row_reconstruct import Word

    page_box = BBox(x0=0.20, y0=0.70, x1=0.21, y1=0.80)
    reading = BBox(x0=0.70, y0=0.79, x1=0.80, y1=0.80)
    w = Word(text="1,000", bbox=reading, page_bbox=page_box)
    assert w.source_bbox is page_box
    # An upright word has one box and it serves both purposes.
    assert Word(text="x", bbox=page_box).source_bbox is page_box


def test_the_dominant_direction_wins_over_a_stray_rotated_stamp():
    """A watermark or a sideways stamp must not decide the whole page's orientation."""
    from app.services.pdf_extract import text_rotation

    class FakePage:
        def __init__(self, lines):
            self._lines = lines

        def get_text(self, kind):
            assert kind == "dict"
            return {"blocks": [{"lines": self._lines}]}

    body = [{"dir": (1.0, 0.0), "spans": [{"text": "x" * 400}]}]
    stamp = [{"dir": (0.0, -1.0), "spans": [{"text": "CONFIDENTIAL"}]}]
    assert text_rotation(FakePage(body + stamp)) == 0
    # ...but a genuinely sideways page is detected.
    sideways = [{"dir": (0.0, -1.0), "spans": [{"text": "y" * 400}]}]
    assert text_rotation(FakePage(sideways + [{"dir": (1.0, 0.0),
                                               "spans": [{"text": "page 12"}]}])) == 90


def test_the_equity_statement_must_close_at_the_balance_sheets_equity():
    """The one relation that crosses two statements — and worth checking precisely because the
    two sides are extracted by completely different readers (a matrix reader and a two-column
    reader), so their agreement is evidence rather than a restatement."""
    from app.api.routes.documents import _accounting_checks, _equity_closing

    def equity_rows(closing):
        return [
            {"source_label": "At 1 January 2023", "canonical_key": None, "values": [
                _val("Retained profits", 1), _val("Total equity", 36_625_241)]},
            {"source_label": "Loss for the year", "canonical_key": None, "values": [
                _val("Retained profits", -1), _val("Total equity", -16_142_915)]},
            {"source_label": "At 31 December 2023", "canonical_key": None, "values": [
                _val("Retained profits", 0), _val("Total equity", closing)]},
        ]

    def bs_equity(total):
        return [{"canonical_key": "bs_equity__total_equity", "source_label": "Total equity",
                 "values": [{"basis": "consolidated", "period_label": "current",
                             "value": str(total)}]}]

    # The LAST balance line is the closing one, not the opening one.
    assert _equity_closing(equity_rows(20_482_326), "consolidated") == (
        "At 31 December 2023", 20_482_326.0)

    # Agreement is silent.
    agreeing = equity_rows(20_482_326) + bs_equity(20_482_326)
    assert [c["type"] for c in _accounting_checks(agreeing, [], "en")] == []

    # Disagreement is a finding that names the gap.
    conflicting = equity_rows(20_482_326) + bs_equity(19_000_000)
    tie = next(c for c in _accounting_checks(conflicting, [], "en") if c["type"] == "equity_tie")
    assert tie["delta"] == "1,482,326"


def test_no_equity_statement_means_no_cross_statement_check():
    """A filing whose equity statement was not extracted must not be accused of anything."""
    from app.api.routes.documents import _accounting_checks, _equity_closing

    rows = [{"canonical_key": "bs_equity__total_equity", "source_label": "Total equity",
             "values": [{"basis": "consolidated", "period_label": "current", "value": "100"}]}]
    assert _equity_closing(rows, "consolidated") is None
    assert [c["type"] for c in _accounting_checks(rows, [], "en")] == []

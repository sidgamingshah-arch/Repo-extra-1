"""Every extraction path that CAN know a row's section now records it.

Fixing the condensed-banner defect on the PDF path exposed that the section was reaching the
residual sweep from only one of three places that produce rows:

* **Excel** — ``excel_extract`` runs a row loop of its own and never set ``section_hint``. Worse, a
  heading row was DISCARDED: ``_row_item`` returns None when a row stores no value, so the banner was
  destroyed at read time rather than merely unused. The module's docstring claims parity with the PDF
  path and enumerates what parity covers (note column, basis band, period selection, units, column
  guard) — sections were never on that list.
* **Notes** — ``notes_extract`` DOES call ``build_line_items``, so the section was always computed
  correctly, and the conversion to ``NoteItem`` then threw it away because the model had no field for
  it. ``residual._sweep_notes`` synthesises face rows from note items, so every figure sourced from a
  note reached the sweep with no section.

Both matter because ``mapping._in_section`` admits every concept when it has no section to compare
against, and ``residual._section_of_row``'s first signal is the row's own banner. With no section the
gate is open and the sweep is down to accounting structure alone.

The Excel banner test is deliberately STRICTER than the PDF one, and
``test_a_line_item_with_no_figures_is_not_a_banner`` is why: "label column has text, value columns
empty" is a heading sometimes and an item with no data for either period the rest of the time. A
spreadsheet has no geometry to break the tie, so the label must be EXHAUSTED by section phrases
(``mapping.section_of_banner_only``) rather than merely contain one.

The statement of changes in equity is deliberately excluded — see ``test_the_equity_matrix_is_out_of
_scope_by_design``.
"""
from __future__ import annotations

import io
import json
import pathlib

import openpyxl
import pytest

from app.core.models.geometry import BBox
from app.services.excel_extract import extract_workbook
from app.services.mapping import (HEADING_ROW_SECTIONS, SECTION_WORDS, normalize_label,
                                  section_of_banner, section_of_banner_only)
from app.services.notes_extract import extract_note_tables
from app.services.row_reconstruct import Word

ONTOLOGY_PATH = (pathlib.Path(__file__).resolve().parent.parent
                 / "app/sample/templates/hkfrs_hk_china_ontology.json")


# ── the banner test itself ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label, token", [
    ("CURRENT ASSETS", "current_assets"),
    ("Current assets", "current_assets"),
    ("流動資產", "current_assets"),
    ("Current assets 流動資產", "current_assets"),          # both languages in one cell
    ("Non-current assets", "non_current_assets"),
    ("CURRENT LIABILITIES", "current_liabilities"),
    ("Equity", "equity"),
    ("Capital and reserves", "equity"),
    ("Operating activities", "cash_flow_from_operating_activities"),
    ("投資活動", "cash_flow_from_investing_activities"),
])
def test_a_heading_is_recognised(label, token):
    assert section_of_banner_only(label) == token


@pytest.mark.parametrize("label", [
    "Equity investments designated at FVOCI",   # a NON-CURRENT ASSET that contains "equity"
    "Equity holders of the parent",
    "Total current assets",                     # a subtotal: the LAST row of its section
    "流动资产总额",
    "Net current assets/(liabilities)",
    "长期负债的流动部分",                            # a CURRENT liability that contains 长期负债
    "Trade receivables",
    "EQUITY AND LIABILITIES",                   # umbrella: scopes nothing on its own
    "Revenue",                                  # `income` is matched on a line-item caption
    "Turnover",
    "Taxation",
    "Other comprehensive income",
    "Profit attributable to owners of the parent",
])
def test_a_caption_is_not_a_heading(label):
    """The whole point of requiring the label to be exhausted by section phrases. Several of these
    ARE recognised by `section_of_banner`, which is correct where geometry has already established
    the text is a standalone heading and wrong where it has not."""
    assert section_of_banner_only(label) is None


def test_the_restriction_to_heading_row_sections_is_load_bearing():
    """`Revenue` and `Taxation` are exhausted by a section phrase — "revenue" IS the whole label —
    so exhaustiveness alone does not refuse them. The token allow-list is the second condition, and
    without it a data-less "Revenue" row would declare the income section for everything below."""
    for label in ("Revenue", "Turnover", "Taxation"):
        token = section_of_banner(label)
        assert token is not None, f"{label} is expected to match loosely"
        assert token not in HEADING_ROW_SECTIONS
        remaining = normalize_label(label)
        for _tok, words in SECTION_WORDS:
            for word in words:
                remaining = remaining.replace(word, " ")
        assert not remaining.strip(), f"{label} IS exhausted, so only the allow-list refuses it"


def test_no_rulebook_caption_is_mistaken_for_a_heading():
    """The corpus sweep, as on the PDF path. Not one of the 185 concepts' captions may read as a
    heading — each is a line a filing prints WITH figures, and mistaking one scopes every row under
    it."""
    doc = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    captions: list[str] = []
    for concept in doc["mappings"]:
        captions.append(concept.get("label") or "")
        captions += concept.get("aliases") or []
        captions += (concept.get("aliases_i18n") or {}).get("zh") or []
    offenders = sorted({c for c in captions if c.strip() and section_of_banner_only(c)})
    assert not offenders, f"these concept captions would be read as section headings: {offenders}"


# ── the Excel path ─────────────────────────────────────────────────────────────────────────────
def _workbook(*sheets: tuple[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _excel_sections(*sheets) -> dict[str, str | None]:
    return {li.source_label: li.section_hint
            for li in extract_workbook(_workbook(*sheets), document_id="d1")}


BALANCE_SHEET = [
    ["Consolidated statement of financial position", None, None],
    [None, "2024", "2023"],
    ["NON-CURRENT ASSETS", None, None],
    ["Property, plant and equipment", 12000, 11000],
    ["Equity investments designated at FVOCI", 500, 400],
    ["CURRENT ASSETS", None, None],
    ["Inventories", 1234, 5678],
    ["Trade receivables", 3410, 2900],
    ["Total current assets", 4644, 8578],
    ["CURRENT LIABILITIES", None, None],
    ["Trade payables", 2000, 1800],
]


def test_an_excel_heading_row_scopes_the_rows_beneath_it():
    got = _excel_sections(("Balance Sheet", BALANCE_SHEET))
    assert got["Property, plant and equipment"] == "NON-CURRENT ASSETS"
    assert got["Inventories"] == "CURRENT ASSETS"
    assert got["Trade receivables"] == "CURRENT ASSETS"
    assert got["Trade payables"] == "CURRENT LIABILITIES"


def test_a_line_item_with_no_figures_is_not_a_banner():
    """The case that forces the stricter test, and it has to be read by the row that FOLLOWS the
    offender — a false banner is harmless if a real one replaces it on the very next line, so the
    damage only shows where a genuine item sits in between.

    Under the loose test this row is consumed as a heading (so its own row disappears) AND scopes
    Goodwill to equity, while being a non-current asset itself."""
    got = _excel_sections(("Balance Sheet", [
        [None, "2024", "2023"],
        ["NON-CURRENT ASSETS", None, None],
        ["Property, plant and equipment", 12000, 11000],
        ["Equity investments designated at FVOCI", None, None],    # no figures either period
        ["Goodwill", 3000, 3000],
    ]))
    # Only the FOLLOWING row can show it: a row with no figures for any period is dropped by
    # `_row_item` whether or not it is read as a banner, so its own absence proves nothing.
    assert got["Goodwill"] == "NON-CURRENT ASSETS", (
        "a data-less line item declared its own section for the rows below it")


def test_a_subtotal_row_does_not_open_a_new_section():
    """"Total current assets" ends its section; it does not open one. Read as a heading it would
    scope every row after it, so the row below — which is still inside current assets until a real
    banner says otherwise — would be relabelled by a subtotal."""
    got = _excel_sections(("Balance Sheet", [
        [None, "2024", "2023"],
        ["CURRENT ASSETS", None, None],
        ["Inventories", 1234, 5678],
        ["Total current assets", None, None],
        ["Trade payables", 2000, 1800],
    ]))
    assert got["Trade payables"] == "CURRENT ASSETS", (
        "the subtotal was read as a heading and opened a section of its own")


def test_a_heading_printed_with_a_figure_is_kept_as_a_row():
    """A heading is only consumed when it carries no figures. A filing that prints a total against
    the caption still gets its number — dropping it to gain a section would lose data."""
    got = _excel_sections(("Balance Sheet", [
        [None, "2024", "2023"],
        ["CURRENT ASSETS", 4644, 8578],
        ["Inventories", 1234, 5678],
    ]))
    assert "CURRENT ASSETS" in got, "the row was consumed as a banner and its figures lost"


def test_a_section_does_not_leak_across_sheets():
    """A workbook's sheets are separate statements. Without the per-sheet reset the balance sheet's
    last banner would scope the first rows of the cash flow statement."""
    got = _excel_sections(
        ("Balance Sheet", BALANCE_SHEET),
        ("Cash Flow", [[None, "2024", "2023"],
                       ["Profit before tax", 900, 800]]),
    )
    assert got["Profit before tax"] is None, (
        "the previous sheet's banner leaked into this one")


def test_a_cash_flow_activity_heading_is_tracked():
    got = _excel_sections(("Cash Flow", [
        [None, "2024", "2023"],
        ["Operating activities", None, None],
        ["Profit before tax", 900, 800],
        ["Investing activities", None, None],
        ["Interest received", 40, 30],
    ]))
    assert got["Profit before tax"] == "Operating activities"
    assert got["Interest received"] == "Investing activities", (
        "'Interest received' is printed under both operating and investing; the heading is the only "
        "thing that tells them apart")


# ── the notes path ─────────────────────────────────────────────────────────────────────────────
def _note_line(y: float, text: str, *, value: str | None = None) -> list[Word]:
    out, x = [], 0.10
    for token in text.split():
        width = min(0.016 * len(token), 0.60 - x)
        out.append(Word(text=token, bbox=BBox(x0=x, y0=y, x1=x + width, y1=y + 0.011)))
        x += width + 0.005
    if value:
        out.append(Word(text=value, bbox=BBox(x0=0.66, y0=y, x1=0.74, y1=y + 0.011)))
    return out


def test_a_note_item_keeps_the_section_reconstruction_computed():
    """`build_line_items` always got this right; the conversion to NoteItem threw it away because
    the model had no field for it. `residual._sweep_notes` builds face rows from these, so the loss
    reached the sweep."""
    words = [w for line in (
        _note_line(0.100, "15. TRADE AND OTHER RECEIVABLES"),
        _note_line(0.140, "CURRENT ASSETS"),
        _note_line(0.160, "Trade receivables", value="1,234"),
        _note_line(0.180, "Amounts due from related parties", value="3,000"),
    ) for w in line]
    tables = extract_note_tables(words, page_index=3, document_id="d1", source_kind="native")
    got = {it.raw_label: it.section_hint for t in tables for it in t.items}
    assert got["Trade receivables"] == "CURRENT ASSETS"
    assert got["Amounts due from related parties"] == "CURRENT ASSETS"


def test_the_equity_matrix_is_out_of_scope_by_design():
    """`_matrix_items` sets no section, and that is correct rather than an oversight: a statement of
    changes in equity has no banners on its ROW axis — its rows are movements and its sections are
    the component COLUMNS — and the rulebook declares no equity-statement concepts or section scopes
    for a section to be compared against. If either of those ever changes, this test should fail and
    the decision should be revisited."""
    doc = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    assert not [c for c in doc["mappings"] if c["canonical_key"].startswith("eq_")]
    assert not {s for c in doc["mappings"] for s in (c.get("section_scope") or [])
                if s.startswith("eq")}

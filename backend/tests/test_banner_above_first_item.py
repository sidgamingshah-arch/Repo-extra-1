"""A section banner printed directly above its first line item still scopes that item.

THE DEFECT THIS CLOSES, off a real HKFRS condensed balance sheet. The statement prints
"Current assets / 流動資產" immediately above the first current-asset line, close enough that
``_group_rows`` — whose tolerance is deliberately generous so a skewed scan still groups — clusters
the banner into that item's row. The row then carries a value, so the label-only banner branch never
sees it, and the same-line heading split above it is gated on a colon this format does not print. The
sticky ``section`` therefore stayed on the PREVIOUS banner, "Non-current assets", and every current
asset and current liability inherited it — which sent the whole block to
``bs_non_current_assets__others`` via the residual stage.

Two mechanisms compounded and both are fixed:

* ``_merge_wrapped_labels`` folded a TITLE-CASE banner into the next valued row, because
  ``_looks_like_header`` accepts only ALL-CAPS or a trailing colon. The main loop already
  compensates for that blind spot (``or banner is not None``); the merge, which runs first, did not
  — so a title-case banner never survived to reach the branch that would have used it.
* Row clustering merged the CJK half of a bilingual banner into the item beneath it.
  ``_split_banner_prefix`` recovers it by splitting a row's label words back into the printed lines
  they came from.

The recovery is GEOMETRIC, not lexical, and ``test_a_single_line_caption_never_sets_a_section`` is
the test that matters most: 73 captions in the shipped rulebook begin with a section phrase
("Equity investments designated at FVOCI" — a non-current asset — "Total current assets",
"长期负债的流动部分", "Revenue", "Taxation"). A text prefix scan fires on all of them and hijacks the
section for every row beneath. Requiring the banner to occupy its own printed LINE excludes them by
construction, because each is printed on one line.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.core.models.geometry import BBox
from app.services.mapping import SECTION_WORDS, normalize_label, section_of_banner
from app.services.row_reconstruct import Word, build_line_items

ONTOLOGY_PATH = (pathlib.Path(__file__).resolve().parent.parent
                 / "app/sample/templates/hkfrs_hk_china_ontology.json")

LINE_H = 0.011
LINE_STEP = 0.012          # < the 0.012 row-clustering tolerance, so adjacent lines DO cluster


def _w(text: str, x0: float, y0: float) -> Word:
    return Word(text=text, bbox=BBox(x0=x0, y0=y0, x1=x0 + 0.018 * len(text), y1=y0 + LINE_H))


def _line(y: float, *tokens: str, value: str | None = None) -> list[Word]:
    """One printed line: label tokens from the left margin, an optional figure in the value column.

    Token widths are scaled to fit the label column, because bboxes are NORMALISED to [0,1] and some
    real captions in the corpus run to eleven words — laid out at a fixed per-character width they
    would run off the page and BBox would reject them.
    """
    LABEL_L, LABEL_R = 0.06, 0.64
    per_char = 0.018
    span = sum(per_char * len(t) for t in tokens) + 0.006 * max(len(tokens) - 1, 0)
    scale = min(1.0, (LABEL_R - LABEL_L) / span) if span else 1.0
    out, x = [], LABEL_L
    for t in tokens:
        width = per_char * len(t) * scale
        out.append(Word(text=t, bbox=BBox(x0=x, y0=y, x1=x + width, y1=y + LINE_H)))
        x += width + 0.006 * scale
    if value is not None:
        out.append(_w(value, 0.72, y))
    return out


def _items(*lines: list[Word]):
    words = [w for line in lines for w in line]
    items, _ = build_line_items(words, page_index=0, document_id="d1", source_kind="native")
    return items


def _sections(items) -> list[tuple[str, str | None]]:
    """(caption, section TOKEN) — the token, because that is what residual.py compares, and the raw
    banner text differs between a filing that prints English and one that prints Chinese."""
    return [(li.source_label, section_of_banner(li.section_hint)) for li in items]


def test_a_bilingual_title_case_banner_scopes_the_items_beneath_it():
    """The reported case. Without the fix every row below "Current assets" keeps the non-current
    banner and the whole current-asset block is swept into bs_non_current_assets__others."""
    items = _items(
        _line(0.300, "NON-CURRENT", "ASSETS"),
        _line(0.312, "Goodwill", value="8,000"),
        _line(0.340, "Current", "assets"),          # title case — invisible to _looks_like_header
        _line(0.352, "流動資產"),                     # clustered into the row below it
        _line(0.364, "Inventories", value="1,234"),
        _line(0.376, "Trade", "receivables", value="3,410"),
    )
    got = dict(_sections(items))
    assert got["Goodwill"] == "non_current_assets"
    assert got["Inventories"] == "current_assets", (
        "the first item of the section inherited the previous banner")
    assert got["Trade receivables"] == "current_assets", (
        "the sticky section was never advanced, so the whole block stayed non-current")


def test_a_title_case_english_banner_is_not_swallowed_as_a_wrapped_label():
    """The other half of the fix, isolated. Here the banners are English-only and sit on their own
    well-separated rows, so nothing recovers them geometrically — everything depends on
    ``_merge_wrapped_labels`` refusing to fold them into the row below.

    ``_looks_like_header`` accepts only ALL-CAPS or a trailing colon, so a filing that prints
    "Current assets" in title case had its banner folded into the first item: the caption became
    "Current assets Inventories" and the section was never set at all. The main loop already
    compensates for that blind spot, but the merge runs first, so the banner never reached it.
    """
    # Line spacing of 0.015 puts this in the band where the merge is the ONLY mechanism in play:
    # centres are 0.015 apart so `_group_rows` (tolerance 0.012) keeps the rows separate, while the
    # 0.004 gap is inside `_tight_below`'s 0.6-line-height window so `_merge_wrapped_labels` treats
    # the banner as a wrapped-label candidate. Wider spacing and the merge never fires; narrower and
    # clustering merges the rows first and the geometric recovery covers for it.
    items = _items(
        _line(0.300, "Non-current", "assets"),
        _line(0.315, "Goodwill", value="8,000"),
        _line(0.345, "Current", "assets"),
        _line(0.360, "Inventories", value="1,234"),
        _line(0.375, "Trade", "receivables", value="3,410"),
    )
    captions = [li.source_label for li in items]
    assert captions == ["Goodwill", "Inventories", "Trade receivables"], (
        f"a banner was folded into a caption: {captions}")
    got = dict(_sections(items))
    assert got["Goodwill"] == "non_current_assets"
    assert got["Inventories"] == "current_assets"
    assert got["Trade receivables"] == "current_assets"


def test_a_cjk_only_banner_scopes_the_items_beneath_it():
    """A filing that prints only Chinese banners. Nothing about the fix is English-specific."""
    items = _items(
        _line(0.300, "非流動資產"),
        _line(0.312, "Goodwill", value="8,000"),
        _line(0.340, "流動負債"),
        _line(0.352, "Trade", "payables", value="2,000"),
    )
    got = dict(_sections(items))
    assert got["Goodwill"] == "non_current_assets"
    assert got["Trade payables"] == "current_liabilities"


def test_it_is_not_only_the_balance_sheet():
    """The same clustering merges a cash-flow ACTIVITY banner into its first item, where the
    consequence is an operating add-back resolving to an investing concept."""
    items = _items(
        _line(0.300, "Operating", "activities"),
        _line(0.312, "經營活動"),
        _line(0.324, "Profit", "before", "tax", value="900"),
        _line(0.352, "Investing", "activities"),
        _line(0.364, "投資活動"),
        _line(0.376, "Interest", "received", value="40"),
    )
    got = dict(_sections(items))
    assert got["Profit before tax"] == "cash_flow_from_operating_activities"
    assert got["Interest received"] == "cash_flow_from_investing_activities", (
        "'Interest received' is printed under both operating and investing; the banner is the only "
        "thing that tells the two apart")


def test_a_wrapped_caption_whose_head_is_a_section_word_is_kept_whole():
    """The regression the first two attempts introduced. "Equity" is both the equity banner and the
    first word of "Equity investments designated at FVOCI"; on a wrapped caption the two are the
    same text on the same geometry. Guessing banner truncates a non-current asset to
    "investments designated at FVOCI" and scopes it to equity."""
    items = _items(
        _line(0.300, "Equity"),
        _line(0.312, "investments", "designated", "at", "FVOCI", value="500"),
    )
    assert len(items) == 1
    assert items[0].source_label == "Equity investments designated at FVOCI"
    assert items[0].section_hint is None


def test_an_all_caps_wrapped_caption_is_still_kept_whole():
    """A pre-existing hard-won case: "TOTAL ASSETS LESS CURRENT" / "LIABILITIES" is one caption, not
    a banner plus a caption, and its second line contains a section phrase."""
    items = _items(
        _line(0.300, "TOTAL", "ASSETS", "LESS", "CURRENT"),
        _line(0.312, "LIABILITIES", value="9,000"),
    )
    assert len(items) == 1
    assert items[0].source_label == "TOTAL ASSETS LESS CURRENT LIABILITIES"


def test_a_colon_heading_still_scopes_its_row():
    """The path that already worked must keep working — it is the same `section` variable."""
    items = _items(
        _line(0.300, "Total", "comprehensive", "income", "attributable", "to:", "Owners",
              value="700"),
    )
    assert section_of_banner(items[0].section_hint) == "total_comprehensive_income_attributable_to"


def _corpus_captions() -> list[str]:
    """Every caption the shipped rulebook can present, in both languages."""
    doc = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    out: list[str] = []
    for concept in doc["mappings"]:
        out.append(concept.get("label") or "")
        out += concept.get("aliases") or []
        out += (concept.get("aliases_i18n") or {}).get("zh") or []
    return [c for c in out if c and c.strip()]


def _starts_with_a_section_phrase(caption: str) -> bool:
    folded = normalize_label(caption)
    return any(folded.startswith(w) for _tok, words in SECTION_WORDS for w in words)


def test_the_corpus_contains_captions_a_prefix_scan_would_misread():
    """Guards the premise of the test below. If this ever returns nothing, the corpus changed and
    the next test has stopped proving anything."""
    risky = [c for c in _corpus_captions() if _starts_with_a_section_phrase(c)]
    assert len(risky) > 40, f"expected the corpus to be full of these, found {len(risky)}"
    # The ones whose damage is worst: a real line item that would hijack the section for the whole
    # block beneath it.
    assert any("FVOCI" in c for c in risky)
    assert "长期负债的流动部分" in risky


@pytest.mark.parametrize("caption", sorted(set(
    c for c in _corpus_captions() if _starts_with_a_section_phrase(c))))
def test_a_single_line_caption_never_sets_a_section(caption: str):
    """THE GUARD AGAINST THE LOOSE FIX. Every rulebook caption that begins with a section phrase,
    printed as one line with a figure, must set no section — whatever words it starts with.

    A text prefix scan sets one on all 73 of them. "Equity investments designated at FVOCI" would
    scope itself and every row beneath it to equity while being a non-current asset; "Total current
    assets" is the LAST row of its section and would scope the NEXT one; "Revenue" would put cost of
    sales in the income section. Requiring the banner to occupy its own printed line is what makes
    these unreachable, so this test fails the moment the requirement is relaxed to text.
    """
    items = _items(_line(0.300, *caption.split(), value="1,000"))
    assert items, f"caption produced no line item: {caption!r}"
    for li in items:
        assert li.section_hint is None, (
            f"{caption!r} set section_hint={li.section_hint!r} from its own text; a caption is not "
            f"a banner and every row beneath it would inherit this")

def test_a_banner_beside_its_first_item_on_one_baseline():
    """The second geometry, and the one the original report describes literally: the heading and its
    first item printed on ONE baseline, separated by clear air rather than by a line break.

    The sub-line split cannot see this — one baseline is one printed line — so the remaining line is
    split by horizontal whitespace, the way `_basis_bands` already tells two column captions apart
    from one sentence naming both. Measured on this shape the gap between the banner and the item is
    0.085 of the page width against 0.004 inside either phrase, so `_CAPTION_GAP` separates them with
    two orders of magnitude to spare.
    """
    def baseline(y, banner_tokens, item_tokens, value):
        out, x = [], 0.06
        for t in banner_tokens:
            out.append(_w(t, x, y)); x += 0.018 * len(t) + 0.004
        # Clear air. The item's own column starts here, giving a gap of ~0.09 against the ~0.004
        # spacing inside either phrase — the proportions measured on a real page. Anything under
        # `_CAPTION_GAP` (0.03) is deliberately NOT a split, so this margin is the point.
        x = 0.46
        for t in item_tokens:
            out.append(_w(t, x, y)); x += 0.018 * len(t) + 0.004
        out.append(_w(value, 0.72, y))
        return out

    items = _items(
        _line(0.300, "NON-CURRENT", "ASSETS"),
        _line(0.320, "Goodwill", value="8,000"),
        baseline(0.350, ["Current", "assets", "流動資產"], ["Inventories"], "1,234"),
        _line(0.370, "Trade", "receivables", value="3,410"),
    )
    got = dict(_sections(items))
    assert "Inventories" in got, f"the banner stayed glued to the caption: {list(got)}"
    assert got["Goodwill"] == "non_current_assets"
    assert got["Inventories"] == "current_assets"
    assert got["Trade receivables"] == "current_assets", (
        "the banner printed beside the first item never advanced the sticky section")


def test_a_multi_word_caption_head_that_starts_with_a_section_phrase_is_kept_whole():
    """The regression the first version of this fix shipped, found by an adversarial sweep.

    The one-word rule caught "Equity" but not "Equity investments designated": three words, and it
    contains "equity", so a substring test called it a banner. The caption was truncated to
    "at FVOCI" — which then maps to whatever that tail resembles — and every row below was scoped to
    equity while the row itself is a non-current asset. Exhaustion is what refuses it: "equity" does
    not account for "investments designated".
    """
    items = _items(
        _line(0.300, "Equity", "investments", "designated"),
        _line(0.315, "at", "FVOCI", value="1,234"),
    )
    assert len(items) == 1
    assert items[0].source_label == "Equity investments designated at FVOCI"
    assert items[0].section_hint is None


def test_a_wrapped_subtotal_caption_is_kept_whole():
    """The same flaw, third instance: "Total current assets" contains "current assets" and read as a
    banner would both truncate the subtotal and scope the rows after it."""
    items = _items(
        _line(0.300, "Total", "current"),
        _line(0.315, "assets", value="4,644"),
    )
    assert len(items) == 1
    assert items[0].source_label == "Total current assets"
    assert items[0].section_hint is None

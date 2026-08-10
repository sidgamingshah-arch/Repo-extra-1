"""A caption is scoped by the section banner it was printed under.

Statements reuse one caption across two sections. A property developer prints
"Interest-bearing bank and other borrowings" once under non-current liabilities and again under
current, and "Senior notes and domestic bonds" the same way; "Properties under development"
appears under both asset sections. The words are byte-identical, so the caption alone cannot say
which concept it is — the banner above the row is the only distinguishing evidence on the page,
and without it both rows collapse onto one concept and one of the two figures is lost.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.loader import load_ontology
from app.services.mapping import OntologyMatcher

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"


@pytest.fixture(scope="module")
def matcher() -> OntologyMatcher:
    definition = json.loads((TEMPLATES / "hkfrs_hk_china_ontology.json").read_text())
    return OntologyMatcher(load_ontology(definition), locale="zh")


@pytest.mark.parametrize("caption,banner,expected", [
    ("Interest-bearing bank and 計息銀行及其他貸款 other borrowings",
     "CURRENT LIABILITIES 流動負債", "bs_current_liabilities__current_borrowings"),
    ("Interest-bearing bank and 計息銀行及其他貸款 other borrowings",
     "NON-CURRENT LIABILITIES 非流動負債",
     "bs_non_current_liabilities__non_current_borrowings"),
    ("Senior notes and domestic bonds 優先票據及境內債券",
     "CURRENT LIABILITIES 流動負債", "bs_current_liabilities__cuurent_notes_payable"),
    ("Senior notes and domestic bonds 優先票據及境內債券",
     "NON-CURRENT LIABILITIES 非流動負債",
     "bs_non_current_liabilities__non_current_notes_payable"),
    ("Properties under development 發展中物業", "CURRENT ASSETS 流動資產",
     "bs_current_assets__properties_under_development"),
    ("Properties under development 發展中物業", "NON-CURRENT ASSETS 非流動資產",
     "bs_non_current_assets__properties_under_development"),
])
def test_the_same_caption_resolves_differently_under_each_banner(matcher, caption, banner,
                                                                 expected):
    got = matcher.match(caption, statement="balance_sheet", section=banner)
    assert got.canonical_key == expected


def test_an_umbrella_banner_constrains_nothing(matcher):
    """IFRS statements print "EQUITY AND LIABILITIES" above the Equity / Non-current / Current
    sub-banners. Reading that as the equity section would refuse every liability concept
    beneath it, so a banner naming more than one section scopes nothing."""
    assert matcher._section_of("EQUITY AND LIABILITIES") is None
    got = matcher.match("Trade and bills payables 貿易應付款項及票據",
                        statement="balance_sheet", section="EQUITY AND LIABILITIES")
    assert got.canonical_key == "bs_current_liabilities__current_trade_payables"


def test_an_unrecognised_banner_constrains_nothing(matcher):
    """Same principle as the statement constraint: suppress a confident wrong answer, never
    drop a concept we merely could not place."""
    assert matcher._section_of("ASSETS") is None
    got = matcher.match("Contract liabilities 合同負債", statement="balance_sheet",
                        section="SOMETHING WE DO NOT KNOW")
    assert got.canonical_key == "bs_current_liabilities__contract_liabilities"


def test_a_key_with_no_section_namespace_is_always_allowed(matcher):
    """"TOTAL ASSETS LESS CURRENT LIABILITIES" is printed inside the current-liabilities block
    on a real filing, but its concept belongs to no section."""
    assert matcher._in_section("bs_total_assets", "CURRENT LIABILITIES 流動負債")
    assert matcher._in_section("pl_profit_before_tax", "CURRENT ASSETS")


def test_cash_flow_activities_scope_their_captions(matcher):
    """"Interest received" and "Dividends received" are printed under both operating and
    investing activities."""
    assert not matcher._in_section(
        "cf_cash_flow_from_operating_activities__interest_received",
        "CASH FLOWS FROM INVESTING ACTIVITIES 投資活動所得現金流量")
    assert matcher._in_section(
        "cf_cash_flow_from_investing_activities__interest_received",
        "CASH FLOWS FROM INVESTING ACTIVITIES 投資活動所得現金流量")


def test_the_banner_is_carried_from_the_page_onto_each_row():
    """The gate is worthless unless reconstruction actually records the banner, which it can
    only do by remembering a label-only row before discarding it."""
    from app.core.models.geometry import BBox
    from app.services.row_reconstruct import Word, build_line_items

    def word(text: str, x: float, y: float) -> Word:
        return Word(text=text, bbox=BBox(x0=x, y0=y, x1=x + 0.08, y1=y + 0.01))

    words = [
        word("NON-CURRENT", 0.10, 0.10), word("LIABILITIES", 0.20, 0.10),
        word("Interest-bearing", 0.10, 0.14), word("borrowings", 0.22, 0.14),
        word("9,817,976", 0.70, 0.14),
        word("CURRENT", 0.10, 0.20), word("LIABILITIES", 0.19, 0.20),
        word("Interest-bearing", 0.10, 0.24), word("borrowings", 0.22, 0.24),
        word("10,275,584", 0.70, 0.24),
    ]
    items, _ = build_line_items(words, page_index=0, document_id=None, source_kind="native")
    banners = [li.section_hint for li in items]
    assert banners == ["NON-CURRENT LIABILITIES", "CURRENT LIABILITIES"], banners

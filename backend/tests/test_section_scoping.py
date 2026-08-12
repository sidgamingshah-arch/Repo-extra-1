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


def test_two_concepts_may_claim_the_same_alias_and_the_banner_decides(matcher):
    """The income statement prints "Owners of the parent" and "Non-controlling interests" TWICE
    — once splitting profit for the year, once splitting total comprehensive income. Both
    concepts legitimately claim the bare caption, so the alias index has to keep both: keeping
    one made the other unreachable, and the row came back unmapped even though its concept
    existed."""
    profit = matcher.match("Non-controlling interests 非控股權益", statement="profit_and_loss",
                           section="Profit/(loss) attributable to")
    assert profit.canonical_key == "pl_profit_attributable_to__non_controlling_interests"

    tci = matcher.match("Non-controlling interests 非控股權益", statement="profit_and_loss",
                        section="Total comprehensive loss attributable to")
    assert tci.canonical_key == (
        "pl_total_comprehensive_income_attributable_to__non_controlling_interests")


def test_a_loss_making_filing_still_names_the_comprehensive_income_split(matcher):
    """A filing reporting a loss prints "Total comprehensive LOSS attributable to", and one
    covering both prints "income/(loss)". Matching on the word "income" missed every such
    heading and sent the comprehensive-income split into the profit split."""
    from app.services.mapping import section_of_banner

    for heading in ("Total comprehensive loss attributable to",
                    "Total comprehensive income attributable to",
                    "Total comprehensive income/(loss) attributable to",
                    "下列各項應佔全面虧損總額"):
        assert section_of_banner(heading) == "total_comprehensive_income_attributable_to", heading
    # ...while the profit split is still its own section.
    assert section_of_banner("Profit/(loss) attributable to") == "profit_attributable_to"


def test_a_heading_printed_on_the_same_line_as_its_first_figure_still_scopes_the_rows():
    """Bilingual filings routinely print a heading and its first amount on one line:
    "Total comprehensive loss attributable to: ... Owners of the parent  (1,234)". The heading
    never appears as a label-only row, but it still scopes that row and the ones below it."""
    from app.core.models.geometry import BBox
    from app.services.row_reconstruct import Word, build_line_items

    def word(text: str, x: float, y: float) -> Word:
        return Word(text=text, bbox=BBox(x0=x, y0=y, x1=x + 0.05, y1=y + 0.01))

    words = [
        *[word(t, 0.10 + i * 0.05, 0.10) for i, t in
          enumerate("Profit attributable to: Owners of the parent".split())],
        word("1,000", 0.74, 0.10), word("2,000", 0.86, 0.10),
        *[word(t, 0.10 + i * 0.05, 0.14) for i, t in enumerate("Non-controlling interests".split())],
        word("100", 0.74, 0.14), word("200", 0.86, 0.14),
        *[word(t, 0.10 + i * 0.05, 0.18) for i, t in
          enumerate("Total comprehensive loss attributable to: Owners of the parent".split())],
        word("3,000", 0.74, 0.18), word("4,000", 0.86, 0.18),
        *[word(t, 0.10 + i * 0.05, 0.22) for i, t in enumerate("Non-controlling interests".split())],
        word("300", 0.74, 0.22), word("400", 0.86, 0.22),
    ]
    items, _ = build_line_items(words, page_index=0, document_id=None, source_kind="native")
    hints = [i.section_hint for i in items]
    # The second "Non-controlling interests" is scoped by the comprehensive-income heading, not
    # by the profit heading four rows above it.
    assert hints[1] == "Profit attributable to"
    assert hints[3] == "Total comprehensive loss attributable to"


# --- the income statement's ordinary sections ---------------------------------------------------
# Until these entries existed, section_of_key returned None for 34 of the 173 shipped concepts, so
# a P&L banner scoped nothing and _in_section waved every one of them through.

def test_pl_section_banners_resolve():
    from app.services.mapping import section_of_banner

    assert section_of_banner("REVENUE") == "income"
    assert section_of_banner("Turnover") == "income"
    assert section_of_banner("EXPENSES") == "expenses"
    assert section_of_banner("Non-operating expenses") == "non_operating_expenses"
    assert section_of_banner("Exceptional items") == "exceptional_items"
    assert section_of_banner("Income tax expense") == "tax_expense"
    assert section_of_banner("Taxation") == "tax_expense"


def test_pl_section_keys_resolve_and_the_compound_wins():
    """`section_of_key` matches "_<tok>__" as a substring, and "_non_operating_expenses__" contains
    "_expenses__" — so the compound has to be tested first or every non-operating concept reports
    itself as an ordinary expense."""
    from app.services.mapping import section_of_key

    assert section_of_key("pl_income__revenue_from_operations") == "income"
    assert section_of_key("pl_expenses__cost_of_goods_sold") == "expenses"
    assert section_of_key("pl_non_operating_expenses__finance_costs") == "non_operating_expenses"
    assert section_of_key("pl_exceptional_items__impairment_loss") == "exceptional_items"
    assert section_of_key("pl_tax_expense__current_tax") == "tax_expense"
    # A statement-level total sits in no section and must stay unconstrained.
    assert section_of_key("pl_profit_before_tax") is None


# --- collision families: the banner scopes a key that carries no section namespace ---------------
# `section_of_key` reads the section out of the "_<token>__" in a canonical key, so a
# statement-level key (`pl_profit_for_the_year`) has no section and `_in_section` waves it through
# under every banner. That is right for a subtotal, and wrong for one leaf of a pair the banner is
# the only evidence between.

@pytest.fixture(scope="module")
def v2_matcher() -> OntologyMatcher:
    definition = json.loads((TEMPLATES / "hkfrs_hk_china_v2_ontology.json").read_text())
    return OntologyMatcher(load_ontology(definition, resolve=True), locale="zh")


def test_the_two_bottom_lines_are_separated_only_by_the_banner(v2_matcher):
    """Both P&L bottom lines are statement-level keys with no section namespace, and the caption
    cannot tell them apart: a wrapped "TOTAL COMPREHENSIVE LOSS FOR THE YEAR" reaches the matcher as
    "LOSS FOR THE YEAR", which is an alias of the profit line. The banner is the whole distinction,
    so the profit line is refused under the comprehensive-income banner and nowhere else."""
    assert not v2_matcher._in_section("pl_profit_for_the_year", "TOTAL COMPREHENSIVE")
    assert v2_matcher._in_section("pl_total_comprehensive_income_for_the_year",
                                  "TOTAL COMPREHENSIVE")
    # Every other banner leaves both of them unconstrained, as any statement-level key must be —
    # `section_hint` is the nearest PRECEDING banner, so a bottom line often carries a stale one.
    for banner in ("EXPENSES", "REVENUE", "Profit attributable to", "SOMETHING WE DO NOT KNOW"):
        assert v2_matcher._in_section("pl_profit_for_the_year", banner), banner
        assert v2_matcher._in_section("pl_total_comprehensive_income_for_the_year", banner), banner


def test_a_family_leaf_is_named_by_the_section_in_its_own_key(v2_matcher):
    """Only the two bottom lines need naming by hand; every other family leaf is placed by the
    section already in its canonical key, so the families cost no second copy of that mapping."""
    from app.services.mapping import family_leaf_named_by

    assert family_leaf_named_by("bs_non_current_liabilities__non_current_borrowings",
                                "CURRENT LIABILITIES 流動負債") == (
        "bs_current_liabilities__current_borrowings")
    assert family_leaf_named_by("cf_cash_flow_from_operating_activities__interest_received",
                                "CASH FLOWS FROM INVESTING ACTIVITIES 投資活動") == (
        "cf_cash_flow_from_investing_activities__interest_received")
    # A banner naming the leaf's own section settles nothing — there is nothing to correct.
    assert family_leaf_named_by("bs_current_assets__properties_under_development",
                                "CURRENT ASSETS 流動資產") is None
    # Neither does a concept in no family, nor a banner that names no section.
    assert family_leaf_named_by("bs_current_assets__inventories", "CURRENT LIABILITIES") is None
    assert family_leaf_named_by("pl_profit_for_the_year", "EQUITY AND LIABILITIES") is None


def test_a_balance_sheet_tax_caption_is_not_a_tax_section_banner():
    """"income tax" is excluded from the tax vocabulary on purpose: three BS captions contain it
    and are their own concepts, so matching it here would scope a balance-sheet row to tax_expense
    and refuse every bs_ concept under it."""
    from app.services.mapping import section_of_banner

    assert section_of_banner("Deferred income tax assets") is None
    assert section_of_banner("Prepaid income tax") is None
    assert section_of_banner("Income tax payable") is None


# --- a re-route may only ever correct the SECTION, never the concept ----------------------------
# Each case below was a real, reproduced wrong figure: the family was declared, the banner
# identified exactly one sibling, and the answer was "corrected" onto a different thing at
# confidence 1.0 — with the subtotals still tying, so nothing downstream could see it.

def test_an_ordinary_comprehensive_income_page_title_does_not_restate_profit():
    """The bare word "comprehensive" is the only banner vocabulary for the comprehensive bottom
    line, and it is deliberately broad so "comprehensive loss" matches. An ordinary HKEX page
    title, "STATEMENT OF COMPREHENSIVE INCOME", is captured as the section_hint for every row on
    the page — which re-routed "Profit for the year" onto total comprehensive income for the whole
    statement, collapsing two figures onto one concept and leaving pl_profit_for_the_year empty."""
    from app.services.mapping import family_leaf_named_by

    for banner in ("STATEMENT OF COMPREHENSIVE INCOME",
                   "CONSOLIDATED STATEMENT OF COMPREHENSIVE INCOME",
                   "OTHER COMPREHENSIVE INCOME",
                   "Total comprehensive income attributable to:"):
        assert family_leaf_named_by("pl_profit_for_the_year", banner) is None, banner
        assert family_leaf_named_by("pl_total_comprehensive_income_for_the_year", banner) is None


def test_bonds_payable_is_not_notes_payable_in_the_wrong_section():
    """The template has no current-bonds node, so "CURRENT LIABILITIES" identified exactly one leaf
    — current NOTES payable — and a row printed "Bonds payable" was filed there instead of the
    residual bucket that was the correct answer."""
    from app.services.mapping import family_leaf_named_by

    assert family_leaf_named_by("bs_non_current_liabilities__non_current_bonds_payable",
                                "CURRENT LIABILITIES") is None


def test_only_the_same_thing_in_another_section_may_be_rerouted():
    """The durable guard, independent of whether the family declarations are right: strip the
    section namespace and the current/non-current wording, and the two leaves must be the same
    concept. This is what makes a mistaken future declaration inert rather than dangerous."""
    from app.services.mapping import _is_variant_of

    # Same thing, different section — the entire licence for re-routing.
    assert _is_variant_of("bs_current_liabilities__current_lease_liabilities",
                          "bs_non_current_liabilities__non_current_lease_liabilities")
    assert _is_variant_of("cf_cash_flow_from_operating_activities__interest_received",
                          "cf_cash_flow_from_investing_activities__interest_received")
    assert _is_variant_of("pl_profit_attributable_to__non_controlling_interests",
                          "pl_total_comprehensive_income_attributable_to__non_controlling_interests")
    # Different things that merely resemble a sibling.
    assert not _is_variant_of("bs_non_current_liabilities__non_current_bonds_payable",
                              "bs_current_liabilities__cuurent_notes_payable")
    assert not _is_variant_of("bs_current_liabilities__current_deferred_revenue",
                              "bs_non_current_liabilities__non_current_deferred_income")
    # A statement-level key has no section variant to be confused with.
    assert not _is_variant_of("pl_profit_for_the_year",
                              "pl_total_comprehensive_income_for_the_year")


def test_the_legitimate_variants_still_reroute():
    """The guard must not have disabled the feature it protects."""
    from app.services.mapping import family_leaf_named_by

    assert family_leaf_named_by("bs_non_current_liabilities__non_current_lease_liabilities",
                                "CURRENT LIABILITIES") \
        == "bs_current_liabilities__current_lease_liabilities"
    assert family_leaf_named_by("cf_cash_flow_from_operating_activities__interest_received",
                               "INVESTING ACTIVITIES") \
        == "cf_cash_flow_from_investing_activities__interest_received"
    assert family_leaf_named_by("pl_profit_attributable_to__owners_of_the_parent",
                               "Total comprehensive income attributable to:") \
        == "pl_total_comprehensive_income_attributable_to__owners_of_the_parent"

"""The face-statement lexicon, case by case.

Titles are fed to :func:`_resolve_statement` as candidate lines, which is what the stage does, so a
case here fails for the same reason it would fail on a real filing. The negative table matters as
much as the positive one: positive-only matching cannot separate a statement face from a note
heading, a contents line or auditor prose that quotes the same words, and every entry below was a
page this classifier used to get wrong.
"""
from __future__ import annotations

import pytest

from app.stages.classify import _resolve_statement, _scope_of


def _resolve(*lines: str):
    cands = [{"text": t, "y": float(40 + i * 18), "size": 14.0, "bold": True}
             for i, t in enumerate(lines)]
    return _resolve_statement(cands)


# (title, expected statement, expected oci_combined)
RESOLVES = [
    ("CONSOLIDATED STATEMENT OF PROFIT OR LOSS", "profit_and_loss", False),
    # Ch.18A biotech / pre-revenue issuers: no "profit" and no "comprehensive income" anywhere.
    ("CONSOLIDATED STATEMENTS OF LOSS AND OTHER COMPREHENSIVE LOSS", "profit_and_loss", True),
    ("CONSOLIDATED STATEMENT OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME",
     "profit_and_loss", True),
    ("CONSOLIDATED STATEMENT OF INCOME", "profit_and_loss", False),
    ("CONSOLIDATED INCOME STATEMENT", "profit_and_loss", False),
    ("CONSOLIDATED PROFIT AND LOSS ACCOUNT", "profit_and_loss", False),      # legacy HK GAAP
    ("CONSOLIDATED STATEMENT OF COMPREHENSIVE LOSS", "comprehensive_income", False),
    ("CONSOLIDATED STATEMENT OF FINANCIAL POSITION", "balance_sheet", False),
    ("CONSOLIDATED BALANCE SHEET", "balance_sheet", False),
    ("CONSOLIDATED STATEMENT OF CHANGES IN SHAREHOLDERS' EQUITY", "changes_in_equity", False),
    ("CONSOLIDATED STATEMENT OF CHANGES IN EQUITY (CONTINUED)", "changes_in_equity", False),
    ("CONSOLIDATED CASH FLOW STATEMENT", "cash_flow", False),
    ("綜合損益及其他全面收益表", "profit_and_loss", True),
    ("綜合虧損及其他全面虧損表", "profit_and_loss", True),
    # A continuation page. The old Chinese end-of-line anchor rejected every one of these.
    ("綜合權益變動表(續)", "changes_in_equity", False),
    # Bilingual one-line title — also rejected by an end-of-line anchor.
    ("綜合損益表 CONSOLIDATED STATEMENT OF PROFIT OR LOSS", "profit_and_loss", False),
    ("綜合財務狀況表", "balance_sheet", False),
    ("母公司资产负债表", "balance_sheet", False),
    ("合并所有者权益变动表", "changes_in_equity", False),
    ("合并现金流量表", "cash_flow", False),
    ("母公司利润表", "profit_and_loss", False),
    ("綜合全面收益表", "comprehensive_income", False),
]

# Every one of these matched a face pattern before the negative guard existed.
DOES_NOT_RESOLVE = [
    "NOTES TO THE CONSOLIDATED STATEMENT OF CASH FLOWS",
    "Consolidated Statement of Profit or Loss ............... 62",
    "12. Financial assets at fair value through profit or loss",
    "現金流量表附註",
    "UNAUDITED SUPPLEMENTARY FINANCIAL INFORMATION",
    "Details are set out in the consolidated statement of cash flows on page 88",
]


@pytest.mark.parametrize("title,expected,combined", RESOLVES)
def test_a_real_statement_title_resolves(title, expected, combined):
    statement, oci, matched, _ambig = _resolve(title)
    assert statement == expected, f"{title!r} resolved to {statement!r}"
    assert oci is combined, f"{title!r} oci_combined={oci}"
    assert matched == title


@pytest.mark.parametrize("title", DOES_NOT_RESOLVE)
def test_a_title_that_is_not_a_statement_face_resolves_to_nothing(title):
    assert _resolve(title)[0] is None, f"{title!r} should not resolve to a statement"


def test_a_contents_page_listing_every_statement_resolves_to_nothing():
    """A face page never titles three different statements; a contents page does. Without this the
    contents page started the document's face region, and pages of front matter were read as
    statements."""
    statement, _, _, _ = _resolve(
        "CONSOLIDATED STATEMENT OF PROFIT OR LOSS",
        "CONSOLIDATED STATEMENT OF FINANCIAL POSITION",
        "CONSOLIDATED STATEMENT OF CASH FLOWS",
        "CONSOLIDATED STATEMENT OF CHANGES IN EQUITY")
    assert statement is None


def test_the_topmost_longest_title_wins_not_the_first_in_the_lexicon():
    """Resolution is position-then-length, never list order. A page carries an equity-statement tail
    above a cash-flow title, and the tail is what the page is still showing."""
    statement, _, matched, _ = _resolve(
        "CONSOLIDATED STATEMENT OF CHANGES IN EQUITY (CONTINUED)",
        "CONSOLIDATED STATEMENT OF CASH FLOWS")
    assert statement == "changes_in_equity" and "CHANGES IN EQUITY" in matched

    # …and on one line, the longer match wins: the combined title is a P&L page, not an OCI one.
    statement, oci, _, _ = _resolve(
        "CONSOLIDATED STATEMENT OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME")
    assert statement == "profit_and_loss" and oci is True


def test_a_company_and_its_subsidiaries_is_consolidated_not_company():
    """The scope test used to check `company` first, so a consolidated statement whose title names
    "the Company and its subsidiaries" was tagged company — the wrong set of figures entirely."""
    scope, _cols = _scope_of(
        "Consolidated statement of financial position of the Company and its subsidiaries",
        [], 1.0)
    assert scope == "consolidated"


def test_a_group_and_company_column_pair_is_mixed():
    """HK balance sheets routinely print Group and Company side by side on one page, which is why a
    single scope is not enough to describe them."""
    lines = [{"text": "Group        Company", "y": 0.1, "size": 10.0, "bold": True}]
    scope, cols = _scope_of("Statement of financial position", lines, 1.0)
    assert scope == "mixed" and cols == ["consolidated", "company"]


def test_a_simplified_consolidated_income_title_is_flagged_ambiguous():
    """綜合收益表 is the income statement in Traditional HK usage and comprehensive income in PRC
    Simplified usage. It resolves to profit_and_loss and says so rather than deciding silently."""
    statement, _, _, ambig = _resolve("综合收益表")
    assert statement == "profit_and_loss" and ambig is True
    # A genuine comprehensive-income page still wins on match length, and is not ambiguous.
    statement, _, _, ambig = _resolve("綜合全面收益表")
    assert statement == "comprehensive_income" and ambig is False

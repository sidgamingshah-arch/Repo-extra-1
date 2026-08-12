"""``sign_convention`` is an expectation, and ``temporality``/``unit_of_account`` are an identity.

Three declarations meet in the normalize stage, and they are easy to confuse with each other:

* ``sign_rule`` NORMALISES — "Less:" makes a figure negative, and the ontology author's
  ``flip_if_label_matches`` regexes correct a specific caption. It changes values, and it keeps
  doing so.
* ``sign_convention`` EXPECTS — the rulebook's own words: "a concept whose sign_convention is
  positive_expected or negative_expected but whose loaded value carries the opposite sign is a
  review trigger, not an auto-correction". Silently flipping such a figure would hide the reason it
  arrived wrong (almost always: the row is on the wrong concept) behind a plausible number, while
  the template's subtotal identities quietly stopped meaning anything.
* ``temporality`` + ``unit_of_account`` IDENTIFY the fact — a position at a date or a movement over
  a period. The balance-sheet non-controlling-interests BALANCE and the P&L attribution FLOW share
  their caption word for word, so nothing in the caption stops the period flow being filed on the
  balance sheet, where it is individually plausible and every subtotal still ties. They are
  different facts and must never merge.
"""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.models.document import DocumentModel, PageSource
from app.core.models.enums import Basis
from app.core.models.geometry import Provenance
from app.core.models.line_item import ExtractedValue, LineItem
from app.core.stage import PipelineContext
from app.schemas.loader import load_ontology
from app.stages.normalize import NormalizeStage

_SAMPLES = Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"


@pytest.fixture(scope="module")
def raw_ontology() -> dict:
    return json.loads((_SAMPLES / "hkfrs_hk_china_v2_ontology.json").read_text())


def _ontology(raw: dict):
    return load_ontology(copy.deepcopy(raw), resolve=True)


def _row(label: str, key: str, value: int, statement: str) -> tuple[DocumentModel, LineItem]:
    li = LineItem(source_label=label, canonical_key=key)
    li.set_value(ExtractedValue(value=Decimal(value), value_raw=Decimal(value),
                                basis=Basis.CONSOLIDATED, period_label="current",
                                provenance=Provenance(page_index=0)))
    doc = DocumentModel(filename="f.pdf", locale="en")
    doc.pages = [PageSource(index=0, statement=statement)]
    doc.line_items = [li]
    return doc, li


def _run(doc: DocumentModel, ontology) -> PipelineContext:
    ctx = PipelineContext(raw_bytes=b"")
    ctx.ontology = ontology
    NormalizeStage().run(doc, ctx)
    return ctx


def _value(li: LineItem) -> ExtractedValue:
    return next(iter(li.values.values()))


# --- sign_convention: expected, never coerced --------------------------------------------------

def test_an_expense_arriving_positive_is_flagged_and_left_alone(raw_ontology):
    doc, li = _row("Cost of sales", "pl_expenses__cost_of_goods_sold", 500, "profit_and_loss")
    _run(doc, _ontology(raw_ontology))

    assert _value(li).value == Decimal(500)            # NOT flipped to -500
    assert "sign_opposite_to_expected:negative_expected" in _value(li).confidence.flags
    assert f"sign_opposite_to_expected:{li.canonical_key}" in li.confidence.flags
    assert _value(li).confidence.sign == pytest.approx(0.35)
    assert li.canonical_key == "pl_expenses__cost_of_goods_sold"


def test_the_expectation_is_the_one_the_rulebook_declares(raw_ontology):
    """Editing the section's ``sign_convention`` to "either" has to stop the finding — otherwise
    the field is decoration and the engine is running on a hardcoded opinion of its own."""
    raw = copy.deepcopy(raw_ontology)
    raw["section_defaults"]["pl_s2_expenses"]["sign_convention"] = "either"
    doc, li = _row("Cost of sales", "pl_expenses__cost_of_goods_sold", 500, "profit_and_loss")
    _run(doc, _ontology(raw))

    assert not any(f.startswith("sign_opposite_to_expected") for f in li.confidence.flags)
    assert _value(li).confidence.sign == pytest.approx(1.0)


def test_an_asset_arriving_negative_is_flagged(raw_ontology):
    doc, li = _row("Inventories", "bs_current_assets__inventories", -80, "balance_sheet")
    _run(doc, _ontology(raw_ontology))
    assert "sign_opposite_to_expected:positive_expected" in _value(li).confidence.flags
    assert _value(li).value == Decimal(-80)


def test_a_figure_with_the_expected_sign_is_not_flagged(raw_ontology):
    doc, li = _row("Inventories", "bs_current_assets__inventories", 80, "balance_sheet")
    _run(doc, _ontology(raw_ontology))
    assert li.confidence.flags == []
    assert _value(li).confidence.sign == pytest.approx(1.0)


def test_sign_rule_still_normalises_and_the_expectation_only_judges_the_result(raw_ontology):
    """"Less: cost of sales" printed unsigned is normalised to negative by ``sign_rule`` — and the
    expectation then has nothing to report. The two declarations do different jobs, and the older
    one keeps its job."""
    doc, li = _row("Less: cost of sales", "pl_expenses__cost_of_goods_sold", 500,
                   "profit_and_loss")
    _run(doc, _ontology(raw_ontology))

    assert _value(li).value == Decimal(-500)
    assert not any(f.startswith("sign_opposite_to_expected") for f in li.confidence.flags)


# --- temporality / unit_of_account: the NCI guard ----------------------------------------------

def test_the_pl_attribution_flow_is_never_filed_as_the_equity_balance(raw_ontology):
    """"Non-controlling interests" on the profit-and-loss face, mapped to the equity BALANCE. The
    figure is plausible, the equity total still ties, and the balance sheet is wrong by a year's
    profit attribution. The row keeps its value and provenance and loses the concept."""
    doc, li = _row("Non-controlling interests", "bs_equity__non_controlling_interests", 40,
                   "profit_and_loss")
    ctx = _run(doc, _ontology(raw_ontology))

    assert li.canonical_key is None
    assert _value(li).value == Decimal(40)             # the figure is not destroyed
    flag = next(f for f in li.confidence.flags if f.startswith("balance_flow_confusion:"))
    assert "temporality:instant!=duration" in flag
    assert "unit_of_account:balance!=flow" in flag
    assert "low_mapping_confidence" in li.confidence.flags
    assert any("balance_flow_confusion" in line for line in ctx.logs)


def test_the_same_caption_on_the_balance_sheet_is_left_exactly_where_it_is(raw_ontology):
    doc, li = _row("Non-controlling interests", "bs_equity__non_controlling_interests", 40,
                   "balance_sheet")
    _run(doc, _ontology(raw_ontology))
    assert li.canonical_key == "bs_equity__non_controlling_interests"
    assert not any(f.startswith("balance_flow_confusion") for f in li.confidence.flags)


def test_the_finding_follows_the_declared_temporality_and_unit(raw_ontology):
    """Declare the equity section a duration flow and the same row stops being a confusion — the
    engine is reading the rulebook, not a built-in table of which statement is which."""
    raw = copy.deepcopy(raw_ontology)
    raw["section_defaults"]["bs_s3_equity"]["temporality"] = "duration"
    raw["section_defaults"]["bs_s3_equity"]["unit_of_account"] = "flow"
    doc, li = _row("Non-controlling interests", "bs_equity__non_controlling_interests", 40,
                   "profit_and_loss")
    _run(doc, _ontology(raw))

    assert li.canonical_key == "bs_equity__non_controlling_interests"
    assert not any(f.startswith("balance_flow_confusion") for f in li.confidence.flags)


def test_unit_of_account_alone_is_enough_to_refuse_the_merge(raw_ontology):
    """With the temporality agreeing, the balance-versus-flow difference is the whole finding."""
    raw = copy.deepcopy(raw_ontology)
    raw["section_defaults"]["bs_s3_equity"]["temporality"] = "duration"
    doc, li = _row("Non-controlling interests", "bs_equity__non_controlling_interests", 40,
                   "profit_and_loss")
    _run(doc, _ontology(raw))

    assert li.canonical_key is None
    flag = next(f for f in li.confidence.flags if f.startswith("balance_flow_confusion:"))
    assert "unit_of_account:balance!=flow" in flag and "temporality" not in flag


def test_a_subtotal_is_not_compared_on_units(raw_ontology):
    """``unit_of_account: subtotal`` is neither a balance nor a flow, so a printed total would look
    foreign on every statement it appears on if it were compared."""
    doc, li = _row("Total assets", "bs_total_assets", 900, "balance_sheet")
    _run(doc, _ontology(raw_ontology))
    assert li.canonical_key == "bs_total_assets"
    assert li.confidence.flags == []


def test_a_statement_the_rulebook_says_nothing_about_yields_no_finding(raw_ontology):
    """The statement of changes in equity carries no concepts of its own here, so there is no
    expectation to test a row against — and an absent declaration must not become a guess."""
    doc, li = _row("Non-controlling interests", "bs_equity__non_controlling_interests", 40,
                   "equity_changes")
    _run(doc, _ontology(raw_ontology))
    assert li.canonical_key == "bs_equity__non_controlling_interests"

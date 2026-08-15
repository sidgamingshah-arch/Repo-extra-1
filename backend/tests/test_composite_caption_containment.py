"""The reviewer's composite-caption netting rules, as the engine actually reads them.

Fourteen rules arrived written against ``gross_parent_candidates`` / ``dedicated_children`` /
``double_count_control`` — a vocabulary nothing in this codebase reads, and one ``NettingRule``
rejects outright because it requires ``target_key``. They were translated into the live containment
pair (``is_gross_parent`` + ``children_if_decomposed``), which ``map_ontology._pairs_to_keep_apart``
already enforces. See ``scripts/apply_netting_v2.py`` for the translation and for the four rules
that landed thinner than written.

These tests hold the translation in place. The one that matters most is
``test_a_composite_caption_is_not_an_alias_of_the_narrow_leaf``: before this change, a filing
printing "Trade and other receivables" bound the whole combined amount to
``bs_current_assets__trade_receivables``, because that composite caption was an alias of the narrow
leaf. Put the alias back and that test fails — which is the point of it.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.schemas.loader import resolve_inherits
from app.schemas.ontology import OntologyDefinition
from app.stages.map_ontology import _pairs_to_keep_apart

ONTOLOGY_PATH = (pathlib.Path(__file__).resolve().parent.parent
                 / "app/sample/templates/hkfrs_hk_china_ontology.json")

# The seven containments the translation switched on: each parent is a COMPOSITE PRINTED CAPTION
# that stands instead of a breakdown, so unfiling it when its components appear is correct.
TRANSLATED = {
    "bs_current_assets__prepayments_other_receivables_and_other_assets": 5,
    "bs_current_liabilities__other_payables_and_accruals": 5,
    "bs_current_assets__cash_and_cash_equivalents": 3,
    "bs_non_current_assets__other_non_current_financial_assets": 1,
    "bs_current_liabilities__other_current_financial_liabilities": 3,
    "pl_income__other_income": 3,
    "pl_expenses__other_expenses": 2,
}
# The two the rulebook already carried, which must not be disturbed.
PRE_EXISTING = {"bs_equity__reserves", "pl_exceptional_items__share_of_profit_of_associates_and_jvs"}

# The four rules whose parent is a REPORTED SUBTOTAL, not a composite caption. These must NOT carry
# the containment pair: the guard strips an aggregate's canonical_key once any component is printed,
# and on a filing that prints "Income tax expense" over "Current tax" and "Deferred tax" — which is
# every filing — that deletes the printed total and breaks the subtotal checks. Their double-count
# control is already structural: a subtotal is derived, never summed into its own section.
SUBTOTAL_PARENTS = {
    "pl_tax_expense__total_tax_expense",
    "pl_expenses__total_cost_of_sales",
    "pl_expenses__total_operating_expenses",
    "pl_total_comprehensive_income_for_the_year",
}

# The composite captions that used to sit on a narrow leaf. (caption, narrow leaf, declared parent)
MOVED_CAPTIONS = [
    ("Trade and other receivables",
     "bs_current_assets__trade_receivables",
     "bs_current_assets__prepayments_other_receivables_and_other_assets"),
    ("Trade and other payables",
     "bs_current_liabilities__current_trade_payables",
     "bs_current_liabilities__other_payables_and_accruals"),
]


@pytest.fixture(scope="module")
def ontology() -> OntologyDefinition:
    raw = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    return OntologyDefinition(**resolve_inherits(raw))


@pytest.fixture(scope="module")
def by_key(ontology) -> dict:
    return {m.canonical_key: m for m in ontology.mappings}


def test_a_composite_caption_is_not_an_alias_of_the_narrow_leaf(by_key):
    """The substantive fix. A composite caption must not name a narrow leaf, or the whole combined
    amount binds there and the rest of the rule never gets a chance to run."""
    for caption, leaf, _parent in MOVED_CAPTIONS:
        aliases = [a.strip().lower() for a in by_key[leaf].aliases]
        assert caption.lower() not in aliases, (
            f"{leaf} claims the composite caption {caption!r}; a filing printing it would assign "
            f"the entire combined figure to this narrow leaf")


def test_the_composite_caption_reaches_its_declared_parent(by_key):
    """Having taken the caption off the leaf, something must still recognise it — otherwise the
    figure goes nowhere and the fix has only made coverage worse."""
    for caption, _leaf, parent in MOVED_CAPTIONS:
        m = by_key[parent]
        aliases = [a.strip().lower() for a in m.aliases]
        assert caption.lower() in aliases, f"{parent} does not claim {caption!r}"


def test_every_translated_rule_declares_its_containment(by_key):
    for key, expected_children in TRANSLATED.items():
        m = by_key[key]
        assert m.is_gross_parent, f"{key} is not marked is_gross_parent"
        assert len(m.children_if_decomposed) == expected_children, (
            f"{key} declares {len(m.children_if_decomposed)} children, expected {expected_children}")


def test_every_declared_child_is_a_real_concept(by_key):
    """24 of the keys as written named concepts that do not exist. A child key that resolves to
    nothing is a rule that silently contains nothing."""
    for key, m in by_key.items():
        for child in m.children_if_decomposed:
            assert child in by_key, f"{key} names non-existent child {child}"


def test_no_concept_is_contained_by_two_parents(by_key):
    """A concept cannot be mutually exclusive with two different aggregates at once — the guard
    would have to null it against one while populating it against the other."""
    claimed: dict[str, str] = {}
    for key, m in by_key.items():
        if not m.is_gross_parent:
            continue
        for child in m.children_if_decomposed:
            assert child not in claimed, (
                f"{child} is a child of both {claimed[child]} and {key}")
            claimed[child] = key


def test_a_parent_is_never_its_own_child(by_key):
    """`netting_finance_costs` named `..._interest_expense` as a child of a parent that resolves to
    `..._interest_expense`. Collapsing a rule onto itself is why it was dropped rather than wired."""
    for key, m in by_key.items():
        assert key not in m.children_if_decomposed, f"{key} contains itself"


def test_the_containment_guard_sees_every_new_pair(ontology):
    """The declaration has to reach the stage that enforces it. `_pairs_to_keep_apart` is what
    `map_ontology` consults; a pair it does not return is a pair nothing acts on."""
    pairs = {aggregate for aggregate, _components, _why in _pairs_to_keep_apart(ontology)}
    for key in TRANSLATED:
        assert key in pairs, f"{key} declares containment but the guard does not see it"
    for key in PRE_EXISTING:
        assert key in pairs, f"pre-existing containment {key} was lost"


def test_a_reported_subtotal_never_carries_the_containment_pair(by_key, ontology):
    """The regression that proved the mechanism matters.

    Setting ``is_gross_parent`` on ``pl_tax_expense__total_tax_expense`` made
    ``_enforce_containment`` strip the total's canonical_key as soon as "Deferred tax" appeared on
    the face — so a statement printing a tax charge of 1,200 with a 300 deferred component published
    the 300 and lost the 1,200. ``test_sole_component`` caught it. These four parents are subtotals,
    and a subtotal's exclusivity is already structural.
    """
    aggregates = {a for a, _c, _w in _pairs_to_keep_apart(ontology)}
    for key in SUBTOTAL_PARENTS:
        m = by_key[key]
        assert not m.is_gross_parent, (
            f"{key} is a reported subtotal; marking it a gross parent deletes the printed total "
            f"whenever a component is printed alongside it")
        assert key not in aggregates, f"{key} reaches the containment guard"


def test_a_subtotal_parent_is_still_declared_a_subtotal(by_key):
    """What the four subtotal rules rely on INSTEAD of containment. If one of these ever became a
    plain line, it would start being summed into its own section and the double count the reviewer's
    rule guards against would become real."""
    for key in SUBTOTAL_PARENTS:
        m = by_key[key]
        assert m.unit_of_account == "subtotal", f"{key} is not declared a subtotal"


def test_oci_composition_still_decomposes_only_the_oci_subtotal(ontology):
    """`oci_composition` decomposes the OCI subtotal into its two IAS 1 categories and predates this
    change. Rule 12 would have added a second, overlapping aggregate over the same concept; it is
    now structural instead, so this group must still stand alone and unaltered."""
    pairs = {aggregate: components for aggregate, components, _ in _pairs_to_keep_apart(ontology)}
    assert set(pairs["pl_other_comprehensive_income_for_the_year"]) == {
        "pl_oci__items_not_reclassified", "pl_oci__items_may_be_reclassified"}
    assert "pl_total_comprehensive_income_for_the_year" not in pairs


def test_no_parent_claims_a_caption_another_concept_exclusively_owns(ontology):
    """The rules' ``caption_keywords`` name the captions that TRIGGER a rule, which is not the same
    as naming its parent. Folding them in blindly gave ``pl_expenses__total_cost_of_sales`` the
    alias "Cost of sales" — already the component's — making the commonest caption on a P&L
    ambiguous between a component and its own total. Thirteen such additions were refused; this
    asserts none crept back.

    Shared aliases are legitimate where two concepts are resolved by printed section (``Bank and
    other borrowings`` sits on both borrowings concepts), so the test targets exactly the harmful
    case: an aggregate sharing a caption with a concept it CONTAINS.
    """
    by = {m.canonical_key: m for m in ontology.mappings}
    for m in ontology.mappings:
        if not m.is_gross_parent:
            continue
        parent_aliases = {a.strip().lower() for a in m.aliases}
        for child in m.children_if_decomposed:
            shared = parent_aliases & {a.strip().lower() for a in by[child].aliases}
            assert not shared, (
                f"{m.canonical_key} and its child {child} both claim {sorted(shared)}; the caption "
                f"cannot decide between an aggregate and a component of it")


def test_the_netting_rules_as_written_would_still_be_rejected():
    """Guards the diagnosis, not the fix. If ``NettingRule`` ever grows an optional ``target_key``,
    the reviewer's original file would start loading and silently netting nothing — the failure
    mode that made translation necessary in the first place."""
    from pydantic import ValidationError

    from app.schemas.ontology import NettingRule

    as_written = {"id": "netting_tax_expense", "section": "pl_tax_expense",
                  "gross_parent_candidates": ["pl_tax_expense__income_tax_expense"],
                  "dedicated_children": ["pl_tax_expense__current_tax"],
                  "double_count_control": "mutually exclusive"}
    with pytest.raises(ValidationError):
        NettingRule(**as_written)


def test_the_two_shipped_netting_rules_survived(ontology):
    """The replacement array named neither of them, and they are the only netting the engine
    performs. "Change the netting" should not silently delete the working part."""
    ids = {r.id for r in ontology.netting_rules}
    assert {"cogs_inclusive_of_opex", "gross_expense_note_split"} <= ids

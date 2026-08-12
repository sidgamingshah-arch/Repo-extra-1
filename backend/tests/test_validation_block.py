"""The rulebook's ``validation`` block, and the coverage contract over its results.

Four things the rulebook declares are checked here, each of them by editing the rulebook and
watching the extraction's output change — a block that can be edited with no effect on the engine
is worse than one that says nothing, because the rulebook is the only place a reviewer can look up
what the pipeline is meant to do:

* ``validation.identities`` — 14 authored expressions, each with a severity;
* ``validation.cross_concept_guards`` — 6 pairs that are individually plausible and jointly wrong;
* ``validation.section_reconciliation`` — every section with a reported subtotal must account for
  its printed rows, and a break blocks auto-approval of that section;
* the coverage contract (:mod:`app.services.coverage`) — three buckets, two rates, a skip taxonomy
  and the alarm states, so a run that verified almost nothing cannot report as a clean one.
"""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.models.enums import Basis
from app.core.models.line_item import ExtractedValue, LineItem
from app.schemas.loader import load_ontology, load_template
from app.services import coverage as cov_mod
from app.services.coverage import coverage
from app.services.structural_checks import (
    cross_concept_guards,
    evaluate_structure,
    ontology_identities,
    section_relations,
)

_SAMPLES = Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"


@pytest.fixture(scope="module")
def raw_ontology() -> dict:
    return json.loads((_SAMPLES / "hkfrs_hk_china_v2_ontology.json").read_text())


@pytest.fixture(scope="module")
def template():
    return load_template(json.loads((_SAMPLES / "hkfrs_hk_china_template.json").read_text()))


def _ontology(raw: dict):
    """Loaded the way the extraction worker loads it — RESOLVED, so the section layer is folded
    in and every concept carries its ``sign_convention``."""
    return load_ontology(copy.deepcopy(raw), resolve=True)


def _facts(figures: dict, basis: Basis = Basis.CONSOLIDATED, period: str | None = "current",
           method: str | None = None, computed: bool = False) -> list[LineItem]:
    out = []
    for key, num in figures.items():
        li = LineItem(source_label=key, canonical_key=key, is_computed=computed)
        li.confidence.method = method
        li.set_value(ExtractedValue(value=Decimal(str(num)), value_raw=Decimal(str(num)),
                                    basis=basis, period_label=period))
        out.append(li)
    return out


def _one(report, rule_id: str, status: str | None = None):
    return next(r for r in report.results
                if r.rule_id == rule_id and (status is None or r.status == status))


def _rows(report) -> list[dict]:
    return [r.model_dump(mode="json") for r in report.results]


# --- validation.identities ---------------------------------------------------------------------

def test_every_declared_identity_is_read_and_evaluated(template, raw_ontology):
    """All 14 are built from their authored ``expr``; the one whose expression names terms the
    template has never heard of is reported as that, not dropped."""
    built = ontology_identities(template, _ontology(raw_ontology))
    assert len(built) == len(raw_ontology["validation"]["identities"]) == 14

    broken = {r.id: r.broken for r in built if r.broken}
    assert broken == {"ontology_identity:cf_movement": "unresolved_terms"}
    # The severities are the rulebook's own, not a default.
    by_id = {r.id: r for r in built}
    assert by_id["ontology_identity:bs_balance"].severity == "blocking"
    assert by_id["ontology_identity:bs_capital_employed"].severity == "warning"
    # A signed expression keeps its signs: net current assets SUBTRACTS current liabilities.
    assert by_id["ontology_identity:bs_net_current"].signs == (1, -1)


def test_an_identity_holds_or_breaks_on_the_extracted_figures(template, raw_ontology):
    ont = _ontology(raw_ontology)
    ties = evaluate_structure(template, _facts({
        "bs_current_assets__total_current_assets": 118_662_453,
        "bs_current_liabilities__total_current_liabilities": 131_532_808,
        "bs_net_current_assets_liabilities": -12_870_355,
    }), ontology=ont)
    assert _one(ties, "ontology_identity:bs_net_current").status == "pass"

    broken = evaluate_structure(template, _facts({
        "bs_current_assets__total_current_assets": 118_662_453,
        "bs_current_liabilities__total_current_liabilities": 131_532_808,
        "bs_net_current_assets_liabilities": -11_870_355,
    }), ontology=ont)
    res = _one(broken, "ontology_identity:bs_net_current")
    assert res.status == "fail" and res.kind == "ontology_identity"
    assert res.difference == 1_000_000            # the difference is attached to the finding
    assert res.details["severity"] == "blocking"
    assert broken.failed_assertions


def test_editing_an_expression_changes_what_is_checked(template, raw_ontology):
    """The identity that cannot be evaluated today is the proof: its ``expr`` names three
    shorthand terms (``net_operating``…) that exist in no template. Spell the real keys and the
    same identity starts checking the cash-flow movement."""
    figures = {
        "cf_cash_flow_from_operating_activities__net_cash_from_operating_activities": 5_094_092,
        "cf_cash_flow_from_investing_activities__net_cash_used_in_investing_activities": 4_044_304,
        "cf_cash_flow_from_financing_activities__net_cash_from_financing_activities": -13_389_527,
        "cf_net_increase_decrease_in_cash_and_cash_equivalents": -4_251_131,
    }
    as_shipped = evaluate_structure(template, _facts(figures),
                                    ontology=_ontology(raw_ontology))
    skipped = _one(as_shipped, "ontology_identity:cf_movement")
    assert skipped.status == "skipped"
    assert skipped.details["reason"] == "unresolved_terms"
    assert skipped.details["terms"] == ["net_financing", "net_investing", "net_operating"]

    edited = copy.deepcopy(raw_ontology)
    ident = next(i for i in edited["validation"]["identities"] if i["id"] == "cf_movement")
    ident["expr"] = ("cf_net_increase_decrease_in_cash_and_cash_equivalents = "
                     + " + ".join(k for k in figures
                                  if k != "cf_net_increase_decrease_in_cash_and_cash_equivalents"))
    after = evaluate_structure(template, _facts(figures), ontology=_ontology(edited))
    assert _one(after, "ontology_identity:cf_movement").status == "pass"


def test_the_gross_profit_tie_is_evaluated_under_the_stated_sign_convention(template,
                                                                           raw_ontology):
    """``pl_gross_profit = revenue + cost_of_goods_sold`` is correct arithmetic *because*
    ``global_rules.sign_convention`` stores expenses negative. Rewriting it as a subtraction to
    make it read naturally would pass on a filing whose costs were loaded positive — the one
    defect this identity exists to catch."""
    ont = _ontology(raw_ontology)
    signed = evaluate_structure(template, _facts({
        "pl_income__revenue_from_operations": 1000,
        "pl_expenses__cost_of_goods_sold": -600,
        "pl_gross_profit": 400,
    }), ontology=ont)
    assert _one(signed, "ontology_identity:pl_gross_profit_tie").status == "pass"

    flipped = evaluate_structure(template, _facts({
        "pl_income__revenue_from_operations": 1000,
        "pl_expenses__cost_of_goods_sold": 600,
        "pl_gross_profit": 400,
    }), ontology=ont)
    res = _one(flipped, "ontology_identity:pl_gross_profit_tie")
    assert res.status == "fail" and res.difference == -1200
    assert res.details["sign_suspect"] == "pl_expenses__cost_of_goods_sold"
    # …and the rulebook's own note travels with the finding rather than living only in the JSON.
    assert "sign convention" in res.details["note"]


def test_severity_decides_whether_a_break_caps_confidence(template, raw_ontology):
    """``cf_to_bs_cash`` is authored ``warning``: closing cash disagreeing with the balance-sheet
    line is usually restricted cash swept into cash equivalents, so it is surfaced for review.
    Change the one word in the rulebook and the same break caps the value's confidence instead."""
    from app.core.models.document import DocumentModel
    from app.core.stage import PipelineContext
    from app.stages.structural import FLAG, FLAG_WARNING, StructuralStage

    figures = {"cf_closing_cash_and_cash_equivalents": 100,
               "bs_current_assets__cash_and_cash_equivalents": 90}

    def run(raw: dict):
        doc = DocumentModel(filename="x.pdf")
        doc.line_items = _facts(figures)
        ctx = PipelineContext(raw_bytes=b"")
        ctx.template = template
        ctx.ontology = _ontology(raw)
        StructuralStage().run(doc, ctx)
        item = next(li for li in doc.line_items
                    if li.canonical_key == "cf_closing_cash_and_cash_equivalents")
        return item, next(iter(item.values.values()))

    item, value = run(raw_ontology)
    assert _one_status(item) == FLAG_WARNING
    assert value.confidence.validation is None      # a warning never lowers the signal

    escalated = copy.deepcopy(raw_ontology)
    ident = next(i for i in escalated["validation"]["identities"] if i["id"] == "cf_to_bs_cash")
    ident["severity"] = "blocking"
    item, value = run(escalated)
    assert FLAG in item.confidence.flags
    assert value.confidence.validation == 0.5


def _one_status(item) -> str:
    return next(f for f in item.confidence.flags if f.startswith("structural_"))


# --- validation.cross_concept_guards -----------------------------------------------------------

def test_all_six_guards_resolve_into_something_evaluable(raw_ontology):
    guards = cross_concept_guards(_ontology(raw_ontology))
    assert len(guards) == len(raw_ontology["validation"]["cross_concept_guards"]) == 6
    assert [g.broken for g in guards] == [""] * 6
    assert {g.predicate for g in guards} == {
        "sign_expectation", "consolidation_eliminated", "mutually_exclusive",
        "equal_while_third_non_zero", "equal_values"}


def test_subsidiaries_on_a_consolidated_column_is_caught_though_the_arithmetic_ties(
        template, raw_ontology):
    """Consolidation eliminates investments in subsidiaries, so its presence never breaks a
    subtotal — the balance sheet ties perfectly and the column is simply the company-only one.
    No arithmetic can reach this."""
    ont = _ontology(raw_ontology)
    key = "bs_non_current_assets__investments_in_subsidiaries"
    guard = f"guard:consolidation_eliminated:{key}"

    consolidated = evaluate_structure(template, _facts({key: 4_500_000}), ontology=ont)
    res = _one(consolidated, guard)
    assert res.status == "fail" and res.details["basis"] == "consolidated"
    assert res.details["violations"] == [{"key": key, "value": "4500000",
                                          "basis": "consolidated"}]

    company = evaluate_structure(template, _facts({key: 4_500_000}, basis=Basis.STANDALONE),
                                 ontology=ont)
    # Nothing to say about a company-only column, and the guard says so rather than passing.
    assert _one(company, guard).status == "skipped"
    assert _one(company, guard).details["reason"] == "precondition_absent"


def test_an_aggregate_loaded_with_its_own_components_is_caught(template, raw_ontology):
    """The template's equity rollup lists ``reserves`` alongside share premium and the rest, so
    loading both double-counts equity and the balance still ties."""
    ont = _ontology(raw_ontology)
    guard = "guard:mutually_exclusive:bs_equity__reserves"

    both = evaluate_structure(template, _facts({
        "bs_equity__reserves": 900, "bs_equity__share_premium": 500,
    }), ontology=ont)
    res = _one(both, guard)
    assert res.status == "fail"
    assert res.details["violations"][0]["components"] == ["bs_equity__share_premium"]

    aggregate_only = evaluate_structure(template, _facts({"bs_equity__reserves": 900}),
                                        ontology=ont)
    assert _one(aggregate_only, guard).status == "pass"


def test_the_components_a_mutual_exclusion_guard_checks_come_from_the_rulebook(template,
                                                                              raw_ontology):
    """"…together with any of its listed components" points at
    ``global_rules.mutually_exclusive_groups``. Shorten that list and the guard stops objecting."""
    ont = _ontology(raw_ontology)
    facts = {"bs_equity__reserves": 900, "bs_equity__share_premium": 500}
    guard = "guard:mutually_exclusive:bs_equity__reserves"
    assert _one(evaluate_structure(template, _facts(facts), ontology=ont), guard).status == "fail"

    edited = copy.deepcopy(raw_ontology)
    group = next(g for g in edited["global_rules"]["mutually_exclusive_groups"]
                 if g["aggregate"] == "bs_equity__reserves")
    group["components"] = [c for c in group["components"] if c != "bs_equity__share_premium"]
    after = evaluate_structure(template, _facts(facts), ontology=_ontology(edited))
    assert _one(after, guard).status == "pass"


def test_the_combined_associates_line_with_a_separate_line_is_caught(template, raw_ontology):
    ont = _ontology(raw_ontology)
    res = _one(evaluate_structure(template, _facts({
        "pl_exceptional_items__share_of_profit_of_associates_and_jvs": -120,
        "pl_exceptional_items__share_of_profits_and_losses_of_associates": -80,
    }), ontology=ont), "guard:mutually_exclusive:"
        "pl_exceptional_items__share_of_profit_of_associates_and_jvs")
    assert res.status == "fail"


def test_a_concept_carrying_the_opposite_of_its_expected_sign_is_caught(template, raw_ontology):
    ont = _ontology(raw_ontology)
    guard = "guard:sign_expectation"

    clean = evaluate_structure(template, _facts({
        "bs_non_current_assets__property_plant_and_equipment": 1000,   # positive_expected
        "pl_expenses__cost_of_goods_sold": -600,                       # negative_expected
    }), ontology=ont)
    assert _one(clean, guard).status == "pass"

    wrong = evaluate_structure(template, _facts({
        "bs_non_current_assets__property_plant_and_equipment": -1000,
        "pl_expenses__cost_of_goods_sold": 600,
    }), ontology=ont)
    res = _one(wrong, guard)
    assert res.status == "fail"
    assert res.details["violations_keys"] == [
        "bs_non_current_assets__property_plant_and_equipment", "pl_expenses__cost_of_goods_sold"]
    assert {v["expected"] for v in res.details["violations"]} == {"positive_expected",
                                                                 "negative_expected"}


def test_profit_equal_to_comprehensive_income_while_oci_is_non_zero_is_caught(template,
                                                                             raw_ontology):
    """The wrapped-caption confusion: both bottom lines carry the same figure, which is only
    possible when OCI is nil. With OCI reported non-zero one of the two is the other's value."""
    ont = _ontology(raw_ontology)
    guard = "guard:equal_while_third_non_zero:pl_profit_for_the_year"
    collision = {
        "pl_profit_for_the_year": -8_401_124,
        "pl_total_comprehensive_income_for_the_year": -8_401_124,
        "pl_other_comprehensive_income_for_the_year": -499_675,
    }
    assert _one(evaluate_structure(template, _facts(collision), ontology=ont),
                guard).status == "fail"

    nil_oci = {**collision, "pl_other_comprehensive_income_for_the_year": 0}
    assert _one(evaluate_structure(template, _facts(nil_oci), ontology=ont),
                guard).status == "pass"

    without_oci = {k: v for k, v in collision.items()
                   if k != "pl_other_comprehensive_income_for_the_year"}
    unknown = _one(evaluate_structure(template, _facts(without_oci), ontology=ont), guard)
    assert unknown.status == "skipped" and unknown.details["reason"] == "precondition_absent"


def test_an_equity_balance_equal_to_a_profit_flow_is_caught(template, raw_ontology):
    res = _one(evaluate_structure(template, _facts({
        "bs_equity__non_controlling_interests": 1_234,
        "pl_profit_attributable_to__non_controlling_interests": 1_234,
    }), ontology=_ontology(raw_ontology)),
        "guard:equal_values:bs_equity__non_controlling_interests")
    assert res.status == "fail"


def test_renaming_the_concept_in_a_guard_changes_what_is_compared(template, raw_ontology):
    """The guard's operands are read out of the sentence, so the sentence is the check."""
    edited = copy.deepcopy(raw_ontology)
    guards = edited["validation"]["cross_concept_guards"]
    at = next(i for i, g in enumerate(guards) if "investments_in_subsidiaries" in g)
    guards[at] = guards[at].replace("bs_non_current_assets__investments_in_subsidiaries",
                                    "bs_non_current_assets__interests_in_associates")

    report = evaluate_structure(
        template, _facts({"bs_non_current_assets__interests_in_associates": 500}),
        ontology=_ontology(edited))
    moved = _one(report, "guard:consolidation_eliminated:"
                         "bs_non_current_assets__interests_in_associates")
    assert moved.status == "fail"
    assert not [r for r in report.results if "investments_in_subsidiaries" in r.rule_id]


def test_a_guard_whose_wording_matches_no_predicate_is_reported_as_a_defect(template,
                                                                           raw_ontology):
    """A guard the engine cannot recognise must not read as a guard that found nothing."""
    edited = copy.deepcopy(raw_ontology)
    edited["validation"]["cross_concept_guards"].append(
        "bs_total_assets ought to look about right for a company of this size.")

    report = evaluate_structure(template, _facts({"bs_total_assets": 100}),
                                ontology=_ontology(edited))
    stray = next(r for r in report.results if r.rule_id.startswith("guard:unrecognised"))
    assert stray.status == "skipped" and stray.details["reason"] == "guard_unrecognised"
    alarms = coverage(_rows(report)).alarms
    assert any(a["code"] == cov_mod.ALARM_PIPELINE_DEFECT
               and a["reason"] == "guard_unrecognised" for a in alarms)


# --- validation.section_reconciliation ---------------------------------------------------------

def test_a_section_that_accounts_for_its_rows_reconciles(template, raw_ontology):
    report = evaluate_structure(template, _facts({
        "pl_income__revenue_from_operations": 900,
        "pl_income__other_income": 100,
        "pl_income__total_income": 1000,
    }), ontology=_ontology(raw_ontology))
    res = _one(report, "section_reconciliation:pl_s1_income")
    assert res.status == "pass" and res.details["blocks_auto_approval"] is True
    # The residual bucket was never printed, so it is nil rather than unknown.
    assert res.details["assumed_zero"] == ["pl_income__others"]


def test_an_unaccounted_row_leaves_an_unallocated_gap(template, raw_ontology):
    report = evaluate_structure(template, _facts({
        "pl_income__revenue_from_operations": 900,
        "pl_income__total_income": 1000,
    }), ontology=_ontology(raw_ontology))
    res = _one(report, "section_reconciliation:pl_s1_income")
    assert res.status == "fail" and res.difference == 100
    # The fact the rulebook says a break emits, carrying the difference.
    assert res.details["unallocated_gap"] == "100"
    assert any("does not reconcile" in a for a in report.failed_assertions)


def test_a_section_reconciles_to_its_closing_subtotal_not_its_first_one(template, raw_ontology):
    """The operating cash-flow section prints two subtotals — "cash generated from operations",
    then "net cash from operating activities" after interest and tax paid. Only the closing one is
    the figure every row in the section feeds; reconciling to the first reports a phantom gap
    equal to the interest and tax."""
    rel = next(r for r in section_relations(template, _ontology(raw_ontology))
               if r.id == "section_reconciliation:cf_s1_cash_flow_from_operating_activities")
    assert rel.target == ("cf_cash_flow_from_operating_activities__"
                          "net_cash_from_operating_activities")
    assert ("cf_cash_flow_from_operating_activities__cash_generated_from_operations"
            not in rel.components)


def test_emptying_the_section_reconciliation_rule_removes_the_check(template, raw_ontology):
    facts = _facts({"pl_income__revenue_from_operations": 900, "pl_income__total_income": 1000})
    assert section_relations(template, _ontology(raw_ontology))

    silenced = copy.deepcopy(raw_ontology)
    silenced["validation"]["section_reconciliation"] = ""
    report = evaluate_structure(template, facts, ontology=_ontology(silenced))
    assert section_relations(template, _ontology(silenced)) == []
    assert not [r for r in report.results if r.kind == "section_reconciliation"]


def test_a_section_with_no_reported_subtotal_is_unreconciled_not_failed(template, raw_ontology):
    """The rulebook's own answer for this case: itemised, flagged unreconciled — never a gap
    invented against a subtotal that was not printed."""
    report = evaluate_structure(template, _facts({
        "pl_profit_attributable_to__owners_of_the_parent": 700,
        "pl_profit_attributable_to__non_controlling_interests": 300,
    }), ontology=_ontology(raw_ontology))
    res = _one(report, "section_reconciliation:pl_s6_profit_attributable_to")
    assert res.status == "skipped" and res.details["reason"] == "no_reported_subtotal"
    buckets = coverage(_rows(report)).aggregate.skips
    assert buckets.get("NO_REPORTED_SUBTOTAL")


def test_the_tolerance_is_one_rounding_unit_per_contributing_row(template, raw_ontology):
    """``residual_framework.reconciliation.tolerance`` is authored per contributing row, because a
    section spread over many printed rows may be a unit out on each of them."""
    figures = {"pl_income__revenue_from_operations": 900, "pl_income__other_income": 100,
               "pl_income__total_income": 1003}
    ont = _ontology(raw_ontology)
    assert _one(evaluate_structure(template, _facts(figures), ontology=ont),
                "section_reconciliation:pl_s1_income").status == "pass"

    flat = copy.deepcopy(raw_ontology)
    flat["residual_framework"]["reconciliation"]["tolerance"] = "one rounding unit"
    strict = _one(evaluate_structure(template, _facts(figures), ontology=_ontology(flat)),
                  "section_reconciliation:pl_s1_income")
    assert strict.status == "fail"


def test_a_failed_section_reconciliation_blocks_auto_approval_of_that_section(template,
                                                                             raw_ontology):
    """"Blocks auto-approval" has to bite on something. It bites here: every value in the
    unreconciled section is held below the auto-accept confidence, so no figure in it can be
    accepted without a reviewer — while a tying section is untouched."""
    from app.config import get_settings
    from app.core.models.document import DocumentModel
    from app.core.stage import PipelineContext
    from app.stages.structural import FLAG_SECTION, StructuralStage

    doc = DocumentModel(filename="x.pdf")
    doc.line_items = _facts({
        "pl_income__revenue_from_operations": 900,      # section is 100 short of its subtotal
        "pl_income__total_income": 1000,
        "pl_tax_expense__current_tax": -50,             # this section ties
        "pl_tax_expense__total_tax_expense": -50,
    })
    ctx = PipelineContext(raw_bytes=b"")
    ctx.template = template
    ctx.ontology = _ontology(raw_ontology)
    StructuralStage().run(doc, ctx)

    threshold = get_settings().extraction.auto_accept_confidence
    unreconciled = next(li for li in doc.line_items
                        if li.canonical_key == "pl_income__revenue_from_operations")
    assert FLAG_SECTION in unreconciled.confidence.flags
    assert next(iter(unreconciled.values.values())).confidence.overall < threshold

    tied = next(li for li in doc.line_items if li.canonical_key == "pl_tax_expense__current_tax")
    assert FLAG_SECTION not in tied.confidence.flags
    assert next(iter(tied.values.values())).confidence.overall >= threshold
    assert any(log.startswith("structural:auto_approval_blocked=") for log in ctx.logs)


# --- the coverage contract ---------------------------------------------------------------------

def _row(rule_id: str, status: str, statement: str = "balance_sheet", reason: str = "",
         kind: str = "rollup", **details) -> dict:
    return {"rule_id": rule_id, "kind": kind, "status": status, "scope_key": "consolidated/current",
            "details": {"statement": statement, "reason": reason, **details}}


def test_three_passes_and_eleven_skips_do_not_report_as_a_hundred_percent():
    """The collapse this module exists to prevent. Of the relations that ran, all held — and
    almost nothing ran, which is the number that matters."""
    rows = [_row(f"p{i}", "pass") for i in range(3)]
    rows += [_row(f"s{i}", "skipped", reason="components_not_mapped") for i in range(11)]

    report = coverage(rows)
    bs = report.statements["balance_sheet"]
    assert (bs.buckets.passed, bs.buckets.failed, bs.buckets.skipped) == (3, 0, 11)
    assert bs.validation_rate == 1.0          # of what ran
    assert bs.coverage_rate == round(3 / 14, 4)
    assert bs.status == cov_mod.PARTIAL       # never PASSED while a declarable relation is unrun
    # Both rates travel together, always: the validation rate alone IS pass/(pass+fail).
    emitted = bs.as_dict()
    assert ("validation_rate" in emitted) == ("coverage_rate" in emitted)
    assert "pass_rate" not in emitted and "score" not in emitted
    assert "3/14" in report.headline() and "3/3" in report.headline()


def test_the_denominator_counts_the_relations_the_filing_makes_answerable():
    """A skip whose cause is thin extraction stays in the denominator — better extraction would
    recover it. A statement the filing does not contain at all drops out of it: a standalone-only
    filing has no cash flow, and holding that against coverage would make every filing partial."""
    rows = [
        _row("r1", "pass"),
        _row("r2", "skipped", reason="target_not_extracted"),
        _row("r3", "skipped", reason="derived_input"),
        _row("r4", "skipped", reason="no_reported_subtotal"),
        _row("r5", "skipped", statement="cash_flow", reason="statement_absent"),
    ]
    report = coverage(rows)
    bs = report.statements["balance_sheet"]
    assert bs.skips == {"INPUT_ABSENT": 1, "TAUTOLOGICAL": 1, "NO_REPORTED_SUBTOTAL": 1}
    assert bs.declarable == 4 and bs.evaluated == 1
    assert report.statements["cash_flow"].declarable == 0
    assert report.statements["cash_flow"].status == cov_mod.ABSENT
    # The aggregate carries the same three buckets, not a re-derived summary.
    assert report.aggregate.declarable == 4
    assert (report.aggregate.buckets.passed, report.aggregate.buckets.skipped) == (1, 4)


def test_the_two_unrecoverable_skips_are_split_from_the_recoverable_ones():
    """One belongs in an improvement backlog; the other says the relation can never catch an
    error however good extraction gets, and the counts have to say which is which."""
    rows = [_row("a", "skipped", reason="components_not_mapped"),
            _row("b", "skipped", reason="derived_input"),
            _row("c", "skipped", reason="unresolved_terms")]
    bs = coverage(rows).statements["balance_sheet"]
    assert bs.recoverable_skips == 1
    assert bs.skips["TAUTOLOGICAL"] == 1 and bs.skips["UNEVALUABLE_RULE"] == 1


def test_a_statement_with_nothing_evaluated_reports_unvalidated_and_never_passed():
    rows = [_row(f"s{i}", "skipped", reason="components_not_mapped") for i in range(4)]
    report = coverage(rows)
    bs = report.statements["balance_sheet"]
    assert bs.status == cov_mod.UNVALIDATED
    assert bs.status != cov_mod.PASSED
    # 0/0 is not 1.0 — reporting it as 1.0 is exactly how nothing-verified reads as verified.
    assert bs.validation_rate is None and bs.coverage_rate == 0.0
    assert report.unvalidated() == ["balance_sheet"]
    assert any(a["code"] == cov_mod.ALARM_UNVALIDATED for a in report.alarms)


def test_more_tautological_skips_than_checks_is_flagged():
    rows = [_row("ok", "pass"),
            *[_row(f"t{i}", "skipped", reason="derived_input") for i in range(2)]]
    alarms = coverage(rows).alarms
    assert any(a["code"] == cov_mod.ALARM_TAUTOLOGY and a["statement"] == "balance_sheet"
               for a in alarms)

    healthy = coverage([_row("ok1", "pass"), _row("ok2", "pass"),
                        _row("t", "skipped", reason="derived_input")])
    assert not [a for a in healthy.alarms if a["code"] == cov_mod.ALARM_TAUTOLOGY]


def test_an_unconditional_guard_reporting_skipped_is_a_pipeline_defect():
    """A guard needing nothing from the filing cannot be unevaluable because of the filing."""
    rows = [_row("guard:mutually_exclusive:x", "skipped", kind="guard",
                 reason="precondition_absent", precondition="always")]
    alarms = coverage(rows).alarms
    assert any(a["code"] == cov_mod.ALARM_PIPELINE_DEFECT
               and a["rule_id"] == "guard:mutually_exclusive:x" for a in alarms)

    conditional = coverage([_row("guard:equal_values:y", "skipped", kind="guard",
                                 reason="precondition_absent",
                                 precondition="both concepts extracted and non-zero")])
    assert not [a for a in conditional.alarms
                if a["code"] == cov_mod.ALARM_PIPELINE_DEFECT]


def test_a_skip_reason_nobody_classified_still_counts_and_raises_an_alarm():
    """A new skip reason must not quietly leave the denominator and inflate coverage."""
    report = coverage([_row("x", "skipped", reason="something_new"), _row("y", "pass")])
    bs = report.statements["balance_sheet"]
    assert bs.skips == {cov_mod.UNCLASSIFIED: 1} and bs.declarable == 2
    assert any(a["code"] == cov_mod.ALARM_PIPELINE_DEFECT for a in report.alarms)


def test_coverage_of_a_real_report_is_dominated_by_what_was_not_verified(template, raw_ontology):
    """Ten cash-flow figures off a real filing: the relations that run hold, and the report says
    plainly how small a share of the declared structure that is."""
    report = evaluate_structure(template, _facts({
        "cf_cash_flow_from_operating_activities__net_cash_from_operating_activities": 5_094_092,
        "cf_cash_flow_from_investing_activities__net_cash_used_in_investing_activities": 4_044_304,
        "cf_cash_flow_from_financing_activities__net_cash_from_financing_activities": -13_389_527,
        "cf_net_increase_decrease_in_cash_and_cash_equivalents": -4_251_131,
        "cf_opening_cash_and_cash_equivalents": 8_156_453,
        "cf_s4_effect_of_foreign_exchange_rate_changes": 26_703,
        "cf_closing_cash_and_cash_equivalents": 3_932_025,
    }), ontology=_ontology(raw_ontology))

    cov = coverage(_rows(report))
    cash = cov.statements["cash_flow"]
    assert cash.buckets.passed and cash.buckets.failed == 0
    assert cash.status == cov_mod.PARTIAL and cash.coverage_rate < 0.5
    # The balance sheet and P&L are absent from this spread, so they neither pass nor count.
    assert cov.statements["balance_sheet"].status == cov_mod.ABSENT
    assert cov.statements["balance_sheet"].declarable == 0
    # Every row is in exactly one of the three buckets — nothing is unaccounted for.
    assert cov.aggregate.buckets.total == len(report.results)


def test_a_real_run_against_the_v2_rulebook_carries_its_declared_relations(client):
    """End to end through the worker: selecting the v2 rulebook means its identities, guards and
    section reconciliations are in the run's stored result — and a v1 rulebook, which declares no
    ``validation`` block at all, is unaffected."""
    import time

    from tests.fixtures.generate import make_native_pdf

    doc_id = client.post("/api/v1/documents",
                         files={"file": ("bs.pdf", make_native_pdf(),
                                         "application/pdf")}).json()["id"]
    onts = client.get("/api/v1/ontologies").json()
    ont = next(o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v2")
    tpls = client.get("/api/v1/templates").json()
    tpl = next(t for t in tpls if t["template_key"] == ont["target_template_key"])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    for _ in range(100):
        if client.get(f"/api/v1/documents/{doc_id}/run").json().get("status") == "succeeded":
            break
        time.sleep(0.05)

    structural = client.get(f"/api/v1/documents/{doc_id}/run").json()["result"]["structural"]
    kinds = {r["kind"] for r in structural}
    assert {"ontology_identity", "guard", "section_reconciliation"} <= kinds
    assert {r["status"] for r in structural} <= {"pass", "fail", "skipped"}
    # Every row is classifiable, and coverage over the run is recomputable from the stored rows.
    assert all(r["status"] != "skipped" or r["details"]["reason"] for r in structural)
    report = coverage(structural)
    assert report.aggregate.buckets.total == len(structural)
    assert "coverage_rate=" in report.headline()


def test_a_relation_fed_by_a_gap_closing_value_can_never_pass(template, raw_ontology):
    """``stages.gap_closing`` shows the model the failing subtotal and asks which unplaced rows
    close it, so a relation fed by its output cannot fail. Reporting that as a pass would be
    circular: the answer was derived from the question."""
    ont = _ontology(raw_ontology)
    honest = _facts({"pl_income__revenue_from_operations": 900, "pl_income__total_income": 1000})
    routed = honest + _facts({"pl_income__others": 100}, method="llm_gap_routing")

    tied = _one(evaluate_structure(template, routed, ontology=ont),
                "section_reconciliation:pl_s1_income")
    assert tied.status == "skipped" and tied.details["reason"] == "derived_input"
    assert tied.details["derived"] == ["pl_income__others"]
    # Routed by the section SWEEP instead, the same figure is checked: the residual is the sum of
    # the rows it absorbed, not a plug, so the relation can still fail.
    swept = honest + _facts({"pl_income__others": 100}, method="residual")
    assert _one(evaluate_structure(template, swept, ontology=ont),
                "section_reconciliation:pl_s1_income").status == "pass"

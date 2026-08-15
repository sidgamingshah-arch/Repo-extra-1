"""Translate the reviewer's 14 composite-caption netting rules into the fields the engine reads.

The rules arrived in a shape the rulebook has no reader for: ``gross_parent_candidates`` /
``dedicated_children`` / ``double_count_control``. ``NettingRule`` requires ``target_key`` and
performs containment arithmetic (``net = target − Σ subtract``), which is a different mechanism —
so loading them verbatim is a hard rejection, and a per-concept ``composite_caption_control``
block loads but is read by nothing at all.

What the rules actually ask for is already enforced here, under other names:

  * ``is_gross_parent`` + ``children_if_decomposed`` on a concept — the guard in
    ``app/stages/map_ontology.py`` that stops an aggregate being loaded additively with the
    children it contains. This is the ``double_count_control`` of every rule, verbatim.
  * ``unallocated_gap`` (``app/services/rollups.py``) — the reconciliation status for a difference
    nothing accounts for, which is the rules' "a gap is not Others".
  * ``residual_policy.plug: false`` — already set on all 13 residual buckets, which is the rules'
    "must never be calculated as a balancing plug".

So this script throws switches rather than adding a vocabulary. For each rule it moves the composite
caption OFF the narrow leaf that currently claims it and ONTO the declared parent, and records the
rule's prose where a reviewer and the LLM will both see it.

Which switch depends on what the parent IS, and getting this wrong is destructive — ``mechanism``
carries the distinction:

``containment`` — the parent is a COMPOSITE PRINTED CAPTION that stands INSTEAD of a breakdown.
    "Trade and other receivables" is printed *or* its components are, never both. Here
    ``_enforce_containment`` is right: it strips the aggregate's ``canonical_key`` (retaining value,
    provenance and a ``PARENT_GROSS_EVIDENCE_ONLY`` flag) so the figure cannot be counted twice.

``structural`` — the parent is a REPORTED SUBTOTAL that appears alongside its components as a
    matter of course: income tax expense over current/deferred tax, total cost of sales over its
    components, total comprehensive income over profit and OCI. Unfiling one of those DELETES a
    printed figure from the statement and breaks the subtotal checks that compare it to the sum of
    its parts — ``test_sole_component`` catches exactly that. These rules need no switch: each
    parent is already ``unit_of_account: subtotal`` with a ``derivation``, and a subtotal is never
    summed into its own section, so "mutually exclusive in calculation" already holds by
    construction. Only their prose and exclude hints are recorded.

The reviewer's own wording distinguishes the two: a containment rule says "never assign the
complete combined amount to trade receivables", while the subtotal rules say the components are
"mutually exclusive **in calculation**" and the parent stays "validation evidence" — don't ADD, not
don't KEEP.

Run with --check to report without writing.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ONTOLOGY = pathlib.Path(__file__).resolve().parent.parent / "app/sample/templates/hkfrs_hk_china_ontology.json"

# ── The translation ────────────────────────────────────────────────────────────────────────────
# `parent` and `children` carry CORRECTED canonical_keys: 24 of the keys as written name concepts
# that do not exist. Corrections are pure renames onto the concept the reviewer plainly meant
# (`pl_tax_expense__income_tax_expense` → `..._total_tax_expense`, whose label IS "Income tax
# expense"). Keys naming a concept the rulebook does not have at all are simply absent here — the
# instruction was to work with the existing 185 and add none — and `thin` records what that cost.
#
# `strip_from` is the substantive behaviour change: a composite caption sitting in a NARROW leaf's
# alias list is why a filing printing "Trade and other receivables" dumps the whole combined amount
# into trade receivables. Removing it there and adding it to the parent is the fix; the containment
# pair then keeps parent and children from both counting.
RULES = [
    {
        "id": "netting_trade_and_other_receivables", "mechanism": "containment",
        "parent": "bs_current_assets__prepayments_other_receivables_and_other_assets",
        "children": [
            "bs_current_assets__trade_receivables",
            "bs_current_assets__due_from_related_parties",
            "bs_current_assets__contract_assets",
            "bs_current_assets__prepaid_income_tax",
            "bs_current_assets__other_financial_assets",
        ],
        "captions_en": [
            "Trade and other receivables",
            "Trade receivables, prepayments and other receivables",
            "Deposits, prepayments and other receivables",
        ],
        "captions_zh": ["贸易及其他应收款", "贸易应收款、预付款项及其他应收款", "按金、预付款项及其他应收款"],
        "regex": [
            r"^(?:trade|accounts?)\s+(?:and\s+)?other\s+receivables?$",
            r"^trade\s+receivables?\s*[,]?\s*prepayments?\s+(?:and|&)\s+other\s+receivables?$",
            r"^deposits?\s*[,]?\s*prepayments?\s+(?:and|&)\s+other\s+receivables?$",
            r"^贸易及其他应收款项?$",
            r"^贸易应收款项?[、,，]?预付款项及其他应收款项?$",
        ],
        "exclude_hints": ["non-current", "长期", "非流动", "contract liabilities", "合同负债",
                          "trade and other payables", "贸易及其他应付款"],
        "rule": ("Treat the printed amount as a combined parent. Populate dedicated children only "
                 "from explicit face or note breakdowns. Allocate the difference to the applicable "
                 "other-receivables parent only after all evidenced children have been deducted. "
                 "Never assign the complete combined amount to trade receivables."),
        "residual_treatment": ("Only itemised source rows that remain unclaimed after "
                               "dedicated-child matching may enter the section residual. A "
                               "difference created by an incomplete or unavailable note is an "
                               "unallocated_gap, not Others."),
        "double_count_control": ("The combined parent and its decomposed children are mutually "
                                 "exclusive for calculation."),
        # "Trade and other receivables" is currently an alias of the NARROW leaf.
        "strip_from": {"bs_current_assets__trade_receivables": ["Trade and other receivables"]},
    },
    {
        "id": "netting_trade_and_other_payables", "mechanism": "containment",
        "parent": "bs_current_liabilities__other_payables_and_accruals",
        "children": [
            "bs_current_liabilities__current_trade_payables",
            "bs_current_liabilities__due_to_related_parties",
            "bs_current_liabilities__contract_liabilities",
            "bs_current_liabilities__current_income_tax_liabilities",
            "bs_current_liabilities__other_current_financial_liabilities",
        ],
        "captions_en": [
            "Trade and other payables",
            "Trade payables, other payables and accruals",
            "Other payables and accrued expenses",
        ],
        "captions_zh": ["贸易及其他应付款", "贸易应付款、其他应付款及应计费用", "其他应付款及应计费用"],
        "regex": [
            r"^(?:trade|accounts?)\s+(?:and\s+)?other\s+payables?$",
            r"^trade\s+payables?\s*[,]?\s*other\s+payables?\s+(?:and|&)\s+accruals?$",
            r"^other\s+payables?\s+(?:and|&)\s+accrued\s+expenses?$",
            r"^贸易及其他应付款项?$",
            r"^贸易应付款项?[、,，]?其他应付款项?及应计(?:费用|款项)$",
        ],
        "exclude_hints": ["non-current", "长期", "非流动", "trade and other receivables",
                          "贸易及其他应收款", "contract assets", "合同资产"],
        "rule": ("Treat the printed amount as a combined parent. Populate trade payables and other "
                 "dedicated children only from explicit face or note evidence. Do not allocate the "
                 "complete caption to trade payables."),
        "residual_treatment": ("Only itemised unclaimed rows may sweep. An unexplained gap between "
                               "the combined caption and extracted note components remains an "
                               "unallocated_gap."),
        "double_count_control": ("Use either the combined reported amount or the decomposed "
                                 "children in calculation, never both."),
        "strip_from": {"bs_current_liabilities__current_trade_payables": ["Trade and other payables"]},
    },
    {
        "id": "netting_cash_and_bank_balances", "mechanism": "containment",
        # The parent here IS the cash concept, and it already carries the composite caption
        # correctly — nothing to strip. The containment pair is what stops a combined
        # "Cash and bank balances" figure standing as cash and cash equivalents untouched.
        "parent": "bs_current_assets__cash_and_cash_equivalents",
        "children": [
            "bs_current_assets__restricted_cash",
            "bs_current_assets__pledged_deposits",
            "bs_current_assets__bank_balances_other_than_cash_and_cash_equivalents",
        ],
        "captions_en": ["Cash and bank balances", "Cash at bank and on hand", "Bank balances and cash"],
        "captions_zh": ["现金及银行结余", "银行结余及现金", "银行存款及现金"],
        "regex": [
            r"^cash\s+(?:and|&)\s+bank\s+balances?$",
            r"^cash\s+at\s+bank\s+(?:and|&)\s+on\s+hand$",
            r"^bank\s+balances?\s+(?:and|&)\s+cash$",
        ],
        "exclude_hints": ["cash flow statement", "statement of cash flows", "现金流量表",
                          "cash generated from operations", "经营所得现金"],
        "rule": ("A combined cash and bank balance caption must not automatically populate cash and "
                 "cash equivalents. Remove explicitly disclosed restricted cash, pledged deposits "
                 "and deposits that do not meet the cash-equivalent definition. Populate cash and "
                 "cash equivalents only from the disclosed eligible component or a supported "
                 "reconciliation."),
        "residual_treatment": ("Unclassified bank balances are not Other current assets. Keep them "
                               "in the closest supported bank-balance concept or route to review."),
        "double_count_control": ("Combined cash and bank balances are validation evidence when "
                                 "dedicated cash categories are populated."),
        "strip_from": {},
    },
    {
        "id": "netting_other_financial_assets", "mechanism": "precedence",
        # `bs_non_current_assets__other_financial_assets` → `..._other_non_current_financial_assets`.
        # Three of four children (current FVTPL, and derivative financial assets current and
        # non-current) name concepts the rulebook does not have, so only the non-current parent
        # ends up with a child.
        "parent": "bs_non_current_assets__other_non_current_financial_assets",
        "children": ["bs_non_current_assets__financial_assets_at_fair_value_through_profit_or_loss"],
        "captions_en": ["Other financial assets"],
        "captions_zh": ["其他金融资产"],
        "regex": [r"^other\s+financial\s+assets?$", r"^其他金融资产$"],
        "exclude_hints": ["financial liabilities", "金融负债", "trade receivables", "贸易应收",
                          "cash equivalents", "现金等价物"],
        "rule": ("Specific measurement-category and derivative captions override generic other "
                 "financial assets. Use the generic parent only for source rows that are genuinely "
                 "described as other financial assets and are not claimed by a dedicated category."),
        "residual_treatment": ("Do not sweep a clearly identified financial instrument into general "
                               "Other assets merely because its dedicated concept was not "
                               "initially matched."),
        "double_count_control": ("The generic parent excludes all amounts assigned to dedicated "
                                 "financial-asset concepts."),
        "strip_from": {},
        "thin": ("Current-asset side dropped entirely and three children omitted: this rulebook has "
                 "no derivative-financial-asset concept (current or non-current) and no current "
                 "FVTPL concept. Only the non-current generic parent is wired."),
    },
    {
        "id": "netting_other_financial_liabilities", "mechanism": "precedence",
        # `bs_non_current_liabilities__other_non_current_financial_liabilities` does not exist at
        # all, so the non-current half of this rule has no parent to hang on.
        "parent": "bs_current_liabilities__other_current_financial_liabilities",
        "children": [
            "bs_current_liabilities__current_borrowings",
            "bs_current_liabilities__current_portion_of_long_term_debt",
            "bs_current_liabilities__current_lease_liabilities",
        ],
        "captions_en": ["Other financial liabilities"],
        "captions_zh": ["其他金融负债"],
        "regex": [r"^other\s+financial\s+liabilities$", r"^其他金融负债$"],
        "exclude_hints": ["financial assets", "金融资产", "trade payables", "贸易应付",
                          "contract liabilities", "合同负债"],
        "rule": ("Specific debt, lease and derivative concepts override generic other financial "
                 "liabilities. Current or non-current classification must follow the issuer's "
                 "reported section."),
        "residual_treatment": ("A clearly identified borrowing, lease or derivative item must not "
                               "sweep into Other liabilities."),
        "double_count_control": ("The generic parent excludes all amounts allocated to dedicated "
                                 "financial-liability concepts."),
        "strip_from": {},
        "thin": ("Non-current half dropped: there is no "
                 "`bs_non_current_liabilities__other_non_current_financial_liabilities` concept. "
                 "Derivative financial liabilities omitted on both sides for the same reason."),
    },
    {
        "id": "netting_other_income_and_gains", "mechanism": "containment",
        "parent": "pl_income__other_income",
        "children": [
            "pl_non_operating_expenses__interest_income",
            "pl_exceptional_items__gains_on_asset_disposal",
            "pl_exceptional_items__fair_value_change_gains",
        ],
        "captions_en": ["Other income and gains", "Other income and other gains",
                        "Other income and gains, net"],
        "captions_zh": ["其他收入及收益", "其他收入及其他收益", "其他收入及收益净额"],
        "regex": [r"^other\s+income\s+(?:and|&)\s+(?:other\s+)?gains?(?:\s*[,]?\s*net)?$",
                  r"^其他收入及(?:其他)?收益(?:净额)?$"],
        "exclude_hints": ["total income", "revenue", "营业收入", "总收入", "finance income", "融资收入"],
        "rule": ("Retain the face caption as a gross parent where it combines several income and "
                 "gain categories. Populate dedicated children only from an explicit note "
                 "breakdown. Do not place the entire combined amount into Other income and also "
                 "populate its children."),
        "residual_treatment": ("An itemised note row that does not qualify for a dedicated income "
                               "or gain concept may remain in Other income. A missing note "
                               "component is an unallocated_gap."),
        "double_count_control": ("The face parent is validation evidence when its children are "
                                 "decomposed."),
        "strip_from": {},
        "thin": ("Two children omitted: no government-grants concept and no separate "
                 "foreign-exchange-gain concept exists. `gain_on_disposal_of_assets` and "
                 "`fair_value_gain` were read as the existing signed concepts "
                 "`gains_on_asset_disposal` and `fair_value_change_gains`."),
    },
    {
        "id": "netting_other_expenses_and_losses", "mechanism": "containment",
        "parent": "pl_expenses__other_expenses",
        "children": [
            "pl_exceptional_items__credit_impairment_losses",
            "pl_exceptional_items__asset_impairment_losses",
        ],
        "captions_en": ["Other expenses and losses", "Other operating expenses", "Other expenses, net"],
        "captions_zh": ["其他费用及亏损", "其他经营费用", "其他费用净额"],
        "regex": [r"^other\s+(?:operating\s+)?expenses?(?:\s+(?:and|&)\s+losses?)?(?:\s*[,]?\s*net)?$",
                  r"^其他(?:经营)?费用(?:及亏损)?(?:净额)?$"],
        "exclude_hints": ["administrative expenses", "selling expenses", "finance costs",
                          "income tax expense", "行政费用", "销售费用", "财务费用", "所得税费用"],
        "rule": ("A combined other-expense caption is a parent. Dedicated impairment, fair-value, "
                 "exchange and disposal-loss concepts may be populated only from explicit "
                 "line-item or note evidence."),
        "residual_treatment": ("Only genuinely unclassified itemised expense rows remain in Other "
                               "expenses. Do not use Other expenses to plug a difference to a "
                               "reported operating-expense total."),
        "double_count_control": "Do not add the combined parent to its decomposed children.",
        "strip_from": {},
        "thin": ("Three children omitted: `fair_value_loss`, `foreign_exchange_loss` and "
                 "`loss_on_disposal_of_assets` name no concept. The signed gain concepts were NOT "
                 "substituted — they are already children of netting_other_income_and_gains, and "
                 "one concept cannot be contained by two different parents."),
    },
    {
        "id": "netting_tax_expense", "mechanism": "structural",
        # `pl_tax_expense__income_tax_expense` → `pl_tax_expense__total_tax_expense`.
        # `current_tax` already declares `sole_component_of: pl_tax_expense__total_tax_expense`, so
        # the containment pair completes a relationship the rulebook half-stated.
        "parent": "pl_tax_expense__total_tax_expense",
        "children": ["pl_tax_expense__current_tax", "pl_tax_expense__deferred_tax"],
        "captions_en": ["Income tax expense", "Taxation", "Tax expense"],
        "captions_zh": ["所得税费用", "税项", "税项开支"],
        "regex": [r"^(?:income\s+)?tax(?:ation)?\s*(?:expense|charge|credit)?$",
                  r"^(?:所得税费用|税项|税项开支)$"],
        "exclude_hints": ["income tax paid", "已付所得税", "tax payable", "应付税项",
                          "deferred tax asset", "递延税项资产", "deferred tax liability", "递延税项负债"],
        "rule": ("The face tax amount is the aggregate. Decompose into current and deferred tax "
                 "only from a successfully parsed tax note. Assign the full aggregate to current "
                 "tax only where positive evidence confirms that no deferred-tax component exists."),
        "residual_treatment": ("An unresolved tax-note difference remains an unallocated_gap. It "
                               "must not sweep into Other expenses or Current tax."),
        "double_count_control": ("The total tax expense and its current and deferred components are "
                                 "mutually exclusive in calculation."),
        "strip_from": {},
    },
    {
        "id": "netting_cost_of_sales", "mechanism": "structural",
        "parent": "pl_expenses__total_cost_of_sales",
        "children": ["pl_expenses__cost_of_goods_sold", "pl_expenses__purchases_of_stock_in_trade"],
        "captions_en": ["Cost of sales", "Cost of revenue", "Cost of goods sold"],
        "captions_zh": ["销售成本", "营业成本", "已售货品成本"],
        "regex": [r"^cost\s+of\s+(?:sales|revenue|goods\s+sold)$",
                  r"^(?:销售成本|营业成本|已售货品成本)$"],
        "exclude_hints": ["selling expenses", "distribution expenses", "finance costs",
                          "销售费用", "分销费用", "财务费用"],
        "rule": ("A reported cost-of-sales total must not be added to separately populated "
                 "cost-of-goods-sold or purchase components. Component extraction is permitted only "
                 "when the face presentation shows additive components or the note explicitly "
                 "reconciles to the reported total."),
        "residual_treatment": ("An unexplained difference to cost of sales is an unallocated_gap "
                               "and must not be placed in Other operating costs."),
        "double_count_control": "The aggregate and its components are mutually exclusive for computation.",
        "strip_from": {},
    },
    {
        "id": "netting_operating_expenses", "mechanism": "structural",
        "parent": "pl_expenses__total_operating_expenses",
        "children": [
            "pl_expenses__selling_and_marketing_expenses",
            "pl_expenses__general_and_administrative_expenses",
            "pl_expenses__research_and_development_expenses",
            "pl_expenses__employee_benefits_expense",
            "pl_expenses__depreciation_and_amortisation_expense",
            "pl_expenses__other_operating_costs",
            "pl_expenses__other_expenses",
            "pl_expenses__others",
        ],
        "captions_en": ["Total operating expenses", "Operating expenses", "Total operating costs"],
        "captions_zh": ["经营费用总额", "经营费用", "经营成本总额"],
        "regex": [r"^(?:total\s+)?operating\s+(?:expenses|costs)$",
                  r"^(?:经营费用总额|经营费用|经营成本总额)$"],
        "exclude_hints": ["cost of sales", "finance costs", "income tax expense",
                          "销售成本", "财务费用", "所得税费用"],
        "rule": ("The operating-expense total is an aggregate. Use either the aggregate or its "
                 "mutually exclusive components in calculation. By-nature note disclosures must not "
                 "be added to by-function face expenses unless an explicit reconciliation supports "
                 "decomposition."),
        "residual_treatment": ("Operating-expense Others contains only itemised, unclaimed "
                               "operating-expense rows. It must never be calculated as a balancing "
                               "plug."),
        "double_count_control": ("The aggregate and all listed components are mutually exclusive "
                                 "for computation."),
        "strip_from": {},
    },
    {
        "id": "netting_oci_and_total_comprehensive_income", "mechanism": "structural",
        # `pl_other_comprehensive_income__total_other_comprehensive_income` →
        # `pl_other_comprehensive_income_for_the_year`. Distinct from the existing
        # `oci_composition` group, which decomposes the OCI subtotal into its two IAS 1 categories;
        # this one decomposes TOTAL comprehensive income into profit + OCI.
        "parent": "pl_total_comprehensive_income_for_the_year",
        "children": ["pl_profit_for_the_year", "pl_other_comprehensive_income_for_the_year"],
        "captions_en": ["Total comprehensive income for the year", "Total comprehensive income"],
        "captions_zh": ["本年度全面收益总额", "全面收益总额"],
        "regex": [r"^total\s+comprehensive\s+income(?:\s+for\s+the\s+year)?$",
                  r"^(?:本年度全面收益总额|全面收益总额)$"],
        "exclude_hints": ["profit attributable", "应占溢利",
                          "other comprehensive income attributable", "应占其他全面收益"],
        "rule": ("Total comprehensive income is an aggregate of profit for the year and total other "
                 "comprehensive income. Attribution to owners and non-controlling interests is a "
                 "separate decomposition and must not be added to the consolidated total."),
        "residual_treatment": ("Unclassified OCI rows may enter the OCI residual only when "
                               "itemised. A difference to total comprehensive income is an "
                               "unallocated_gap."),
        "double_count_control": ("Do not add total comprehensive income to profit and OCI or to "
                                 "attribution components."),
        "strip_from": {},
    },
]

# Rules 8, 13 and 14 change nothing, for two different reasons. Recorded here so the report
# accounts for all 14 rather than quietly listing 11.
NOT_APPLIED = {
    "netting_finance_costs": (
        "dropped — nothing left to wire. `pl_non_operating_expenses__finance_costs` does not "
        "exist; the concept carrying that label is `..._interest_expense`, which the rule names as "
        "its own first child, so parent and child collapse to one concept. Its other three "
        "children (interest on lease liabilities, bank charges, unwinding of discount) name no "
        "concept."),
    "netting_cash_flow_interest_received": (
        "already enforced — both concepts exist and each already carries "
        "`section_disambiguation` prose binding the caption by printed section. HKAS 7.31 permits "
        "either classification, and neither is a parent of the other, so there is no containment "
        "pair to set."),
    "netting_cash_flow_interest_paid": (
        "already enforced — same shape. The operating concept is already `exclusive_leaf` and both "
        "carry the discriminating prose."),
}


def split_captions(rule: dict) -> tuple[list[str], list[str]]:
    """English captions go to `aliases`/`keyword_hints`; Chinese to `aliases_i18n['zh']`, which is
    where every other concept in this rulebook keeps them."""
    return rule.get("captions_en", []), rule.get("captions_zh", [])


def extend_unique(target: list, additions: list) -> int:
    """Append what isn't already there, preserving order. Returns how many landed."""
    before = len(target)
    seen = set(target)
    for a in additions:
        if a not in seen:
            target.append(a)
            seen.add(a)
    return len(target) - before


def alias_owners(doc: dict, locale: str | None = None) -> dict[str, set[str]]:
    """Every alias in the rulebook → the concepts that claim it. Several captions are claimed by
    more than one concept on purpose (``Bank and other borrowings`` sits on both the current and
    non-current borrowings concepts and is resolved by printed section); this is a map of what is
    already true, not a uniqueness assertion.

    ``locale`` reads ``aliases_i18n[locale]`` instead of the default-locale list. The Chinese set
    needs the same guard as the English one and did not get it on the first pass: 销售成本 is the
    primary Chinese alias of ``pl_expenses__cost_of_goods_sold``, and adding it to
    ``total_cost_of_sales`` as well broke ``test_traditional_only_captions_map`` — the Traditional
    銷售成本 folds to it, so the fold no longer had one answer."""
    owners: dict[str, set[str]] = {}
    for c in doc["mappings"]:
        vals = ((c.get("aliases_i18n") or {}).get(locale) or []) if locale else (c.get("aliases") or [])
        for a in vals:
            owners.setdefault(a.strip().lower(), set()).add(c["canonical_key"])
    return owners


def guard_captions(rule: dict, owners: dict[str, set[str]], moving: set[str],
                   field: str = "captions_en") -> tuple[list, list]:
    """Split a rule's captions into ones safe to give the parent and ones that must be refused.

    A rule's ``caption_keywords`` name the captions that TRIGGER it, which is not the same thing as
    naming its parent. Where the parent is a subtotal, the trigger caption often belongs to the
    component: ``netting_cost_of_sales`` lists "Cost of sales", which is an alias of
    ``pl_expenses__cost_of_goods_sold``, and handing it to ``total_cost_of_sales`` as well would
    make the commonest caption on a P&L ambiguous between a component and its own total. The rule
    does not need it — the containment pair alone stops the two being added together.

    So a caption is refused when a DIFFERENT concept already claims it, unless this rule is
    deliberately moving it off that concept (``strip_from``). Captions nobody claims, and captions
    the parent already claims, are fine."""
    ok, refused = [], []
    for cap in rule.get(field, []):
        held = owners.get(cap.strip().lower(), set()) - {rule["parent"]} - moving
        (refused if held else ok).append((cap, sorted(held)))
    return [c for c, _ in ok], refused


def guard_regex(rule: dict, doc: dict, owners: dict[str, set[str]],
                moving: set[str]) -> tuple[list, list]:
    """Same test for regex hints, which can claim a caption without naming it.

    ``^(?:total\\s+)?operating\\s+(?:expenses|costs)$`` reads as a hint for
    ``pl_expenses__total_operating_expenses`` but also matches "Total operating costs", the primary
    alias of the separate and deliberately confusable ``pl_expenses__total_operating_cost``. A
    regex is refused when it matches any alias in the rulebook the parent does not itself claim."""
    ok, refused = [], []
    for pat in rule.get("regex", []):
        try:
            rx = re.compile(pat, re.IGNORECASE)
        except re.error as exc:                       # a bad pattern is a defect, not a hint
            refused.append((pat, [f"invalid regex: {exc}"]))
            continue
        clash = set()
        for alias, holders in owners.items():
            if not rx.match(alias):
                continue
            outside = holders - {rule["parent"]} - moving
            if outside and rule["parent"] not in holders:
                clash |= outside
        (refused if clash else ok).append((pat, sorted(clash)))
    return [p for p, _ in ok], refused


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report without writing")
    args = ap.parse_args()

    doc = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    by = {c["canonical_key"]: c for c in doc["mappings"]}
    # Snapshot ownership BEFORE any edit, so the guard judges each rule against the shipped
    # rulebook rather than against captions an earlier rule in this same run just added.
    owners = alias_owners(doc)
    owners_zh = alias_owners(doc, locale="zh")

    # Every key must resolve before anything is written — a rulebook half-translated is worse than
    # one not translated at all.
    missing = []
    for r in RULES:
        for k in [r["parent"], *r["children"], *r.get("strip_from", {})]:
            if k not in by:
                missing.append((r["id"], k))
    if missing:
        for rid, k in missing:
            print(f"FATAL {rid}: unknown canonical_key {k}", file=sys.stderr)
        return 2

    report = []
    for r in RULES:
        parent = by[r["parent"]]
        line = {"id": r["id"], "parent": r["parent"], "children": len(r["children"])}

        line["mechanism"] = r["mechanism"]
        if r["mechanism"] == "containment":
            parent["is_gross_parent"] = True
            extend_unique(parent.setdefault("children_if_decomposed", []), r["children"])

        # Captions this rule deliberately takes off a narrow leaf are not "owned elsewhere" for
        # the purpose of the guard — moving them is the whole point.
        moving = set((r.get("strip_from") or {}).keys())

        safe_en, refused_en = guard_captions(r, owners, moving)
        safe_zh, refused_zh = guard_captions(r, owners_zh, moving, field="captions_zh")
        safe_rx, refused_rx = guard_regex(r, doc, owners, moving)
        line["refused"] = refused_en + refused_zh + refused_rx

        line["aliases+"] = extend_unique(parent.setdefault("aliases", []), safe_en)
        if safe_zh:
            i18n = parent.setdefault("aliases_i18n", {})
            line["zh+"] = extend_unique(i18n.setdefault("zh", []), safe_zh)
        if safe_rx:
            rx_list = parent.get("regex_hints")
            if rx_list is None:
                rx_list = parent["regex_hints"] = []
            line["regex+"] = extend_unique(rx_list, safe_rx)
        line["excl+"] = extend_unique(parent.setdefault("exclude_hints", []),
                                      r.get("exclude_hints", []))

        # The rule text belongs where a reviewer and the mapper both already look: containment
        # prose in `aggregation_note`, residual prose in `decomposition_rule`.
        agg = " ".join(x for x in (r.get("rule"), r.get("double_count_control")) if x)
        if agg:
            existing = (parent.get("aggregation_note") or "").strip()
            parent["aggregation_note"] = f"{existing} {agg}".strip() if existing else agg
        if r.get("residual_treatment"):
            existing = (parent.get("decomposition_rule") or "").strip()
            parent["decomposition_rule"] = (f"{existing} {r['residual_treatment']}".strip()
                                            if existing else r["residual_treatment"])

        # The behaviour fix: take the composite caption off the narrow leaf that claims it today.
        stripped = []
        for key, captions in (r.get("strip_from") or {}).items():
            child = by[key]
            for field in ("aliases", "keyword_hints", "regex_hints"):
                vals = child.get(field)
                if not vals:
                    continue
                keep = [v for v in vals if v not in captions]
                if len(keep) != len(vals):
                    stripped += [f"{key}.{field}:{v}" for v in vals if v not in keep]
                    child[field] = keep
        line["stripped"] = stripped
        if r.get("thin"):
            line["thin"] = r["thin"]
        report.append(line)

    print(f"{'rule':46} {'children':>8}  {'alias+':>6} {'zh+':>4} {'rx+':>4} {'ex+':>4}  stripped")
    for line in report:
        print(f"{line['id']:46} {line['children']:>8}  {line.get('aliases+', 0):>6} "
              f"{line.get('zh+', 0):>4} {line.get('regex+', 0):>4} {line.get('excl+', 0):>4}  "
              f"{', '.join(line['stripped']) or '—'}")
    print()
    for line in report:
        for cap, held in line.get("refused") or []:
            print(f"REFUSED {line['id']}: {cap!r} — claimed by {', '.join(held)}")
    print()
    for line in report:
        if line.get("thin"):
            print(f"THIN {line['id']}: {line['thin']}")
    for rid, why in NOT_APPLIED.items():
        print(f"SKIP {rid}: {why}")

    if args.check:
        print("\n--check: nothing written")
        return 0

    # No breadcrumb key: `unknown_keys` refuses anything the schema does not declare (it would be
    # dropped in silence at load), and `metadata.netting_v2_applied` is exactly that. The record of
    # what was applied lives in this script and in tests/test_composite_caption_containment.py.
    # `indent=1` matches the shipped file, so the diff shows the 13 concepts touched and not 8,000
    # reflowed lines.
    ONTOLOGY.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {ONTOLOGY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

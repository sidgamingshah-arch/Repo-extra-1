"""Rewrite the shipped template's income statement and cash flow to the revised specification.

The sibling of ``revise_balance_sheet.py``, and it reuses that script's builders so the two cannot
drift. Every edit is add-or-replace, so running it twice leaves the same files.

WHAT THIS CHANGES, and why each matters:

* THE INCOME STATEMENT BECOMES A LADDER. Gross profit, EBIT, profit before tax and the rest were
  parked at the BOTTOM of the statement, after the attribution captions, because they belong to no
  section. They now sit where a filing prints them — between the sections they are struck from —
  which is the same interleaving the balance-sheet pass introduced.

* COST OF SALES IS ITS OWN SECTION, and gross profit routes through its subtotal. ``pl_gross_profit``
  was ``SUM(revenue, cost_of_goods_sold)``, which is wrong for any filing that prints purchases of
  stock-in-trade as a separate line: the purchases were counted into ``total_operating_cost`` but not
  into gross profit, so the two disagreed by exactly that line and nothing said so.

* EBIT GAINS A FORMULA. ``pl_operating_profit_ebit`` had none — a bare row that stayed empty unless
  the filing printed the caption, which IFRS does not require. It is now
  ``SUM(total_income, total_operating_cost)``, so the statement shows a figure for it on any filing
  that states its income and its costs.

  Precisely how far that reaches, because it is easy to overstate: the grid and the export read
  calculated lines through ``rollups.evaluate``, which is what now fills the row. The KPI layer does
  NOT — ``derived._value`` goes through ``periods.concept_value``, which sums the PRINTED lines
  mapped to a concept — so EBIT interest coverage, EBIT margin and EBITDA still report unavailable
  on a filing that prints no operating-profit line. Feeding computed subtotals to the KPI layer is a
  separate change, and worth making: the grid showing a computed EBIT while the KPIs call it missing
  is one quantity with two answers.

* OTHER COMPREHENSIVE INCOME BECOMES REAL. ``pl_other_comprehensive_income_for_the_year`` was a
  role: subtotal node with no children and no rollup — a plug that could only ever hold a printed
  figure. It now has the two IAS 1.82A categories beneath it and a rollup over them, which is what
  makes the total-comprehensive-income tie checkable from components rather than from one caption.

* THE CASH FLOW GAINS ITS TWO INTERMEDIATE SUBTOTALS (operating profit before working capital
  changes, cash generated from operations), so the operating section reads as HKAS 7 presents it
  rather than as one flat list of sixteen adjustments.

* A SECTION KEY TYPED AS AN ITEM IS RETIRED. ``cf_s4_effect_of_foreign_exchange_rate_changes`` was
  declared ``role: header`` with an empty children array and then USED as a value input to the
  closing-cash rollup. The rulebook carried a ``template_note`` recording exactly this and asking
  for the node role to be corrected; the note is deleted here because the defect is. The key is now
  ``cf_effect_of_foreign_exchange_rate_changes``, ``role: line``.

* ``pl_total_expenses`` IS DELETED. It carried no formula, no children and no place in the revised
  ladder, and it was reachable from two lists in the rulebook (a ``never_sweep`` entry and a
  ``confusable_with`` entry) that had to go with it.

* ONE KEY RENAMED: ``pl_non_operating_expenses__total_non_operating_expense`` →
  ``…__total_non_operating``. The section holds interest INCOME and investment income as well as
  interest expense, so its subtotal is not an expense; two rulebook ``derivation`` sentences and one
  ``never_sweep`` entry named the old spelling and move with it.

* TWELVE NEW CONCEPTS. A template line no rulebook recognises is a line that can never be filled.

* THE MATCHING GATE LEARNS THE OCI BANNER. ``mapping.SECTION_WORDS`` had no entry for other
  comprehensive income, and the new section id ENDS in "income" — so
  ``section_token_of_scope("pl_s8_other_comprehensive_income")`` would have read it as the REVENUE
  section, admitting OCI concepts under a revenue banner and refusing them under their own. The new
  entry is ordered before the total-comprehensive-income one, which contains only "comprehensive"
  and so still matches the attribution banner it is for.

* THE ``interest_paid`` COLLISION FAMILY. "Interest paid" is now a concept in the operating section
  as well as the financing one — the same caption printed under two activities, which is exactly the
  shape ``CONCEPT_FAMILIES`` already carries for "Interest received".

* A CHILD THE FILING DOES NOT PRINT IS NIL, NOT UNKNOWN, WHEN THE RULEBOOK SAYS SO. See
  ``_nil_when_absent`` in ``services/structural_checks.py``: the one engine change here, and the
  thing that keeps the gross-profit tie alive. Without it, splitting cost of sales into two leaves
  plus a subtotal would have retired the most-used check on the income statement.

WHAT THE SPEC ASKS FOR THAT IS NOT ENCODED, and what happens instead:

* THREE CATCH-ALL LINES INSIDE THE OPERATING SECTION. The spec marks ``other_non_cash_adjustments``
  and ``other_working_capital_movements`` as residuals alongside the existing ``others``. The sweep
  is keyed on SECTION — ``stages/residual`` builds ``{r.section: r}`` — so three residuals in one
  section leaves two of them silently unreachable, the survivor decided by position in the file. Both
  new lines are therefore ordinary concepts with their own captions ("Other non-cash adjustments" is
  a line filings print), and the operating section keeps ONE sweep bucket.

* ``COALESCE`` AS AN OPERATOR, at CF row 13 and CHECK 10. Not needed: a missing child is skipped by
  ``rollups.evaluate``, so ``SUM(profit_before_tax, profit_for_the_year, …)`` over two mutually
  exclusive starting lines IS the coalesce, and the new ``cf_starting_point`` exclusivity group is
  what makes a filing that populates both a reported finding rather than a double count. CHECK 10's
  ``COALESCE_MATCHED`` is expressed as two identities — one per starting line — each of which skips
  when its own operands are absent, so exactly one of them ever runs.

* PER-CHECK TOLERANCES (0.5% at CHECK 13, 2% at CHECK 14) and the ``advisory`` SEVERITY at CHECK 14.
  ``ValidationIdentity`` carries ``id``/``expr``/``severity``/``note`` and nothing else, and its
  severity enum is blocking|warning. Both land as ``warning`` on the shared tolerance, with the
  reason for the looser one written into the note where a reviewer reads it.

* ONE ROW BEYOND THE SPEC'S 59, at the user's request after this was reported: ``pl_oci__others``,
  the other-comprehensive-income section's sweep bucket. Every other section on every statement owns
  one; OCI did not, and ``stages/residual`` resolves a row's section by walking to the nearest
  section that HAS a bucket — backwards, when nothing below it does. So an OCI line neither IAS 1
  category claimed (an exchange-translation movement, a hedging reserve movement) was swept into
  ``pl_tax_expense__others``, inside Total tax expense, which then moved profit for the year. The
  income statement is 60 rows.

* ``warn`` FOR THE OCI COMPOSITION (CHECK 8). Same as the balance sheet's reserves composition: the
  rollup asserts it and a rollup has no severity field, so it is blocking. Skip-when-absent already
  matches ``skip_if_either_side_absent``.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from revise_balance_sheet import (ONTOLOGY, TPL, _mapping_index, calc,  # noqa: E402
                                 line, rename_outside_metadata, section, sync_declared_count)

# The two spellings the revision corrects, and the one concept it removes. Renaming reaches further
# than the ``canonical_key`` field: both are named from ``derivation`` prose and ``never_sweep`` /
# ``confusable_with`` lists, which is why the rename is a whole-document walk (see
# ``_rename_everywhere``) rather than a field edit.
KEY_FIXES = {
    "pl_non_operating_expenses__total_non_operating_expense":
        "pl_non_operating_expenses__total_non_operating",
    "cf_s4_effect_of_foreign_exchange_rate_changes": "cf_effect_of_foreign_exchange_rate_changes",
}
DROP_CONCEPTS = {"pl_total_expenses"}


# --- the income statement ----------------------------------------------------------------------
# (key, English label, Chinese label). Section prefixes are applied by `line`.
INCOME = [
    ("revenue_from_operations", "Revenue from operations", "营业收入"),
    ("other_income", "Other income", "其他收入"),
    ("others", "Other income items", "其他收入项目"),
]
COST_OF_SALES = [
    ("cost_of_goods_sold", "Cost of Goods Sold", "销售成本"),
    ("purchases_of_stock_in_trade", "Purchases of Stock-in-trade", "存货采购"),
]
# Order is the spec's: taxes and surcharges first, depreciation before the two "other" captions.
OPERATING_EXPENSES = [
    ("taxes_and_surcharges", "Taxes and surcharges", "税金及附加"),
    ("selling_and_marketing_expenses", "Selling and Marketing Expenses", "销售及市场推广费用"),
    ("general_and_administrative_expenses", "General and Administrative expenses", "一般及行政费用"),
    ("research_and_development_expenses", "Research and development expenses", "研发费用"),
    ("employee_benefits_expense", "Employee benefits expense", "员工福利开支"),
    ("depreciation_and_amortisation_expense", "Depreciation and Amortisation Expense",
     "折旧及摊销费用"),
    ("other_operating_costs", "Other Operating costs", "其他营业成本"),
    ("other_expenses", "Other expenses", "其他开支"),
    ("others", "Other expense items", "其他费用项目"),
]
NON_OPERATING = [
    ("interest_expense", "Interest Expense", "利息支出"),
    ("interest_income", "Interest Income", "利息收入"),
    ("investment_income", "Investment income", "投资收益"),
    ("others", "Others", "其他"),
]
EXCEPTIONAL = [
    ("share_of_profit_of_associates_and_jvs", "share of profit of associates and JVs",
     "应占联营及合营企业利润"),
    ("share_of_profits_and_losses_of_associates", "Share of profits and losses of associates",
     "应占联营公司溢利及亏损"),
    ("share_of_profits_and_losses_of_joint_ventures",
     "Share of profits and losses of joint ventures", "应占合营公司溢利及亏损"),
    ("gain_on_derecognition_of_financial_assets_at_amortised_cost",
     "Gain on derecognition of financial assets at amortised cost",
     "终止确认以摊余成本计量金融资产的收益"),
    ("fair_value_change_gains", "Fair value change gains", "公允价值变动收益"),
    ("gains_on_asset_disposal", "Gains on asset disposal", "资产处置收益"),
    ("credit_impairment_losses", "Credit impairment losses", "信用减值损失"),
    ("asset_impairment_losses", "Asset impairment losses", "资产减值损失"),
    ("others", "Other exceptional items", "其他特殊项目"),
]
# No sweep bucket. Removed at the user's request after a real filing swept loss-per-share into it:
# below-the-line rows kept arriving in the tax charge, where a figure in cents is too small for any
# rollup to notice. A tax row nothing claims now reaches REVIEW instead — eligibility 4 makes a row
# resolved to a section with no bucket ineligible rather than walking it on to the nearest section
# that has one, so removing the bucket does not push those rows into exceptional items.
TAX = [
    ("current_tax", "Current tax", "当期所得税"),
    ("deferred_tax", "Deferred tax", "递延所得税"),
]
OCI_ITEMS = [
    ("items_not_reclassified", "Items that will not be reclassified to profit or loss",
     "不会重分类进损益的项目"),
    ("items_may_be_reclassified",
     "Items that may be reclassified subsequently to profit or loss", "将重分类进损益的项目"),
    # The section's sweep bucket. Without one, an OCI line neither IAS 1 category claimed had no
    # home in its own section and the sweep walked BACKWARDS to the nearest section that did have
    # one — the tax section — so an exchange-translation reserve movement landed inside Total tax
    # expense and moved the P&L bottom line. See `_oci_residual`.
    ("others", "Other comprehensive income items", "其他综合收益项目"),
]
ATTRIBUTION = [
    ("owners_of_the_parent", "Owners of the parent", "母公司拥有人"),
    ("non_controlling_interests", "Non-controlling interests", "非控股权益"),
]


def build_profit_and_loss() -> dict:
    inc, cos, exp = "pl_income", "pl_expenses", "pl_expenses"
    nop, exc, tax, oci = "pl_non_operating_expenses", "pl_exceptional_items", "pl_tax_expense", "pl_oci"

    income_lines = [line(inc, k, en, zh) for k, en, zh in INCOME]
    total_income = calc("pl_income__total_income", "Total income", "收入总额", "sum",
                        [n["canonical_key"] for n in income_lines], "subtotal")

    cos_lines = [line(cos, k, en, zh) for k, en, zh in COST_OF_SALES]
    total_cos = calc("pl_expenses__total_cost_of_sales", "Total cost of sales", "销售成本总额",
                     "sum", [n["canonical_key"] for n in cos_lines], "subtotal")

    exp_lines = [line(exp, k, en, zh) for k, en, zh in OPERATING_EXPENSES]
    total_opex = calc("pl_expenses__total_operating_expenses", "Total operating expenses",
                      "营业费用总额", "sum", [n["canonical_key"] for n in exp_lines], "subtotal")

    nop_lines = [line(nop, k, en, zh) for k, en, zh in NON_OPERATING]
    total_nop = calc("pl_non_operating_expenses__total_non_operating",
                     "Total non-operating income/(expense)", "营业外收支总额", "sum",
                     [n["canonical_key"] for n in nop_lines], "subtotal")

    exc_lines = [line(exc, k, en, zh) for k, en, zh in EXCEPTIONAL]
    total_exc = calc("pl_exceptional_items__total_exceptional_items", "Total Exceptional items",
                     "非经常性项目总额", "sum", [n["canonical_key"] for n in exc_lines], "subtotal")

    tax_lines = [line(tax, k, en, zh) for k, en, zh in TAX]
    total_tax = calc("pl_tax_expense__total_tax_expense", "Total tax expense", "所得税费用总额",
                     "sum", [n["canonical_key"] for n in tax_lines], "subtotal")

    oci_lines = [line(oci, k, en, zh) for k, en, zh in OCI_ITEMS]
    oci_total = calc("pl_other_comprehensive_income_for_the_year",
                     "Other comprehensive income/(loss) for the year", "年内其他全面收益／（亏损）",
                     "sum", [n["canonical_key"] for n in oci_lines], "subtotal")

    total_operating_cost = calc(
        "pl_expenses__total_operating_cost", "Total operating cost", "营业成本总额", "sum",
        [total_cos["canonical_key"], total_opex["canonical_key"]], "subtotal")
    gross_profit = calc("pl_gross_profit", "Gross profit", "毛利", "sum",
                        ["pl_income__revenue_from_operations", total_cos["canonical_key"]], "total")
    ebit = calc("pl_operating_profit_ebit", "Operating Profit / EBIT", "营业利润/息税前利润", "sum",
                [total_income["canonical_key"], total_operating_cost["canonical_key"]], "total")
    pbeit = calc("pl_profit_before_exceptional_items_and_tax",
                 "Profit before exceptional items and tax", "非经常性项目及税前利润", "sum",
                 [ebit["canonical_key"], total_nop["canonical_key"]], "total")
    pbt = calc("pl_profit_before_tax", "Profit before tax", "税前利润", "sum",
               [pbeit["canonical_key"], total_exc["canonical_key"]], "total")
    pfy = calc("pl_profit_for_the_year", "Profit for the year", "年度利润", "sum",
               [pbt["canonical_key"], total_tax["canonical_key"]], "total")
    tci = calc("pl_total_comprehensive_income_for_the_year",
               "Total comprehensive income/(loss) for the year", "年内全面收益／（亏损）总额", "sum",
               [pfy["canonical_key"], oci_total["canonical_key"]], "total")

    return {
        "type": "profit_and_loss",
        "sections": [
            section("pl_s1_income", "Income", "收入", [*income_lines, total_income]),
            section("pl_s2a_cost_of_sales", "Cost of sales", "销售成本", [*cos_lines, total_cos]),
            gross_profit,
            section("pl_s2_expenses", "Operating expenses", "营业费用", [*exp_lines, total_opex]),
            total_operating_cost,
            ebit,
            section("pl_s3_non_operating_expenses", "Non-operating income and expenses", "营业外收支",
                    [*nop_lines, total_nop]),
            pbeit,
            section("pl_s4_exceptional_items", "Exceptional items", "非经常性项目",
                    [*exc_lines, total_exc]),
            pbt,
            section("pl_s5_tax_expense", "Tax expense", "所得税费用", [*tax_lines, total_tax]),
            pfy,
            section("pl_s6_profit_attributable_to", "Profit/(loss) attributable to",
                    "下列各项应占溢利／（亏损）",
                    [line("pl_profit_attributable_to", k, en, zh) for k, en, zh in ATTRIBUTION]),
            section("pl_s8_other_comprehensive_income", "Other comprehensive income", "其他综合收益",
                    [*oci_lines, oci_total]),
            tci,
            section("pl_s7_total_comprehensive_income_attributable_to",
                    "Total comprehensive income/(loss) attributable to",
                    "下列各项应占全面收益／（亏损）总额",
                    [line("pl_total_comprehensive_income_attributable_to", k, en, zh)
                     for k, en, zh in ATTRIBUTION]),
        ],
        # Every relation the revised income statement asserts is a rollup above, and the rulebook
        # authors the attribution ties. Declaring any of them here as well would put one fact in the
        # coverage denominator twice.
        "identities": [],
    }


# --- the cash flow -----------------------------------------------------------------------------
# The operating section in three blocks, in printed order: the adjustments that reach operating
# profit before working capital changes, the working-capital movements that reach cash generated
# from operations, and the payments that reach net cash from operating activities.
CF_ADJUSTMENTS = [
    ("profit_before_tax", "Profit before tax", "税前利润"),
    ("profit_for_the_year", "Profit for the year", "年度利润"),
    ("income_tax_expense", "Income tax expense", "所得税费用"),
    ("depreciation_and_amortisation", "Depreciation and amortisation", "折旧及摊销"),
    ("finance_costs", "Finance costs", "财务费用"),
    ("interest_income", "Interest income", "利息收入"),
    ("share_of_results_of_associates_and_joint_ventures",
     "Share of results of associates and joint ventures", "应占联营及合营企业业绩"),
    ("fair_value_changes_on_financial_instruments",
     "Fair value changes on financial instruments", "金融工具公允价值变动"),
    ("impairment_losses_on_financial_and_contract_assets",
     "Impairment losses on financial and contract assets", "金融及合同资产减值损失"),
    ("loss_gain_on_disposal_of_property_plant_and_equipment",
     "Loss/(gain) on disposal of property, plant and equipment", "处置物业、厂房及设备的亏损／（收益）"),
    ("other_non_cash_adjustments", "Other non-cash adjustments", "其他非现金调整"),
]
CF_WORKING_CAPITAL = [
    ("increase_decrease_in_trade_receivables", "(Increase)/decrease in trade receivables",
     "应收账款的（增加）／减少"),
    ("increase_decrease_in_inventories", "(Increase)/decrease in inventories", "存货的（增加）／减少"),
    ("increase_decrease_in_prepayments_and_other_receivables",
     "(Increase)/decrease in prepayments and other receivables", "预付款项及其他应收款的（增加）／减少"),
    ("increase_decrease_in_trade_payables", "Increase/(decrease) in trade payables",
     "应付账款的增加／（减少）"),
    ("increase_decrease_in_contract_liabilities", "Increase/(decrease) in contract liabilities",
     "合同负债的增加／（减少）"),
    ("increase_decrease_in_other_payables_and_accruals",
     "Increase/(decrease) in other payables and accruals", "其他应付款及应计费用的增加／（减少）"),
    ("other_working_capital_movements", "Other working capital movements", "其他营运资金变动"),
]
CF_OPERATING_TAIL = [
    ("interest_received", "Interest received", "已收利息"),
    ("interest_paid", "Interest paid", "已付利息"),
    ("income_tax_paid", "Income tax paid", "已付所得税"),
    ("others", "Others", "其他"),
]
CF_INVESTING = [
    ("purchase_of_property_plant_and_equipment", "Purchase of property, plant and equipment",
     "购建物业、厂房及设备"),
    ("purchase_of_intangible_assets", "Purchase of intangible assets", "购买无形资产"),
    ("additions_to_investment_properties", "Additions to investment properties", "添置投资物业"),
    ("proceeds_from_disposal_of_property_plant_and_equipment",
     "Proceeds from disposal of property, plant and equipment", "处置物业、厂房及设备所得款项"),
    ("purchase_of_investments", "Purchase of investments", "购买投资"),
    ("proceeds_from_sale_of_investments", "Proceeds from sale of investments", "出售投资所得款项"),
    ("acquisition_of_subsidiaries_net_of_cash_acquired",
     "Acquisition of subsidiaries, net of cash acquired", "收购子公司（扣除所得现金）"),
    ("disposal_of_subsidiaries_net_of_cash_disposed",
     "Disposal of subsidiaries, net of cash disposed", "出售子公司（扣除所付现金）"),
    ("advances_to_related_parties", "Advances to related parties", "向关联方提供的款项"),
    ("dividends_received_from_associates_and_investments",
     "Dividends received from associates and investments", "已收联营公司及投资股息"),
    ("interest_received", "Interest received", "已收利息"),
    ("placement_withdrawal_of_time_deposits", "(Placement)/withdrawal of time deposits",
     "定期存款的（存入）／提取"),
    ("others", "Others", "其他"),
]
CF_FINANCING = [
    ("proceeds_from_borrowings", "Proceeds from borrowings", "借款所得款项"),
    ("repayment_of_borrowings", "Repayment of borrowings", "偿还借款"),
    ("proceeds_from_issue_of_bonds_and_notes", "Proceeds from issue of bonds and notes",
     "发行债券及票据所得款项"),
    ("redemption_of_bonds_and_notes", "Redemption of bonds and notes", "赎回债券及票据"),
    ("principal_elements_of_lease_payments", "Principal elements of lease payments",
     "租赁付款的本金部分"),
    ("interest_paid", "Interest paid", "已付利息"),
    ("proceeds_from_issue_of_shares", "Proceeds from issue of shares", "发行股份所得款项"),
    ("repurchase_of_shares", "Repurchase of shares", "购回股份"),
    ("capital_contributions_from_non_controlling_interests",
     "Capital contributions from non-controlling interests", "非控股权益注资"),
    ("advances_from_related_parties", "Advances from related parties", "关联方提供的款项"),
    ("dividends_paid", "Dividends paid", "已付股利"),
    ("dividends_paid_to_non_controlling_interests", "Dividends paid to non-controlling interests",
     "已付非控股权益股息"),
    ("others", "Others", "其他"),
]


def build_cash_flow() -> dict:
    op = "cf_cash_flow_from_operating_activities"
    inv = "cf_cash_flow_from_investing_activities"
    fin = "cf_cash_flow_from_financing_activities"

    adj = [line(op, k, en, zh) for k, en, zh in CF_ADJUSTMENTS]
    # Both starting lines are children. Exactly one is ever printed, so the sum IS the spec's
    # COALESCE; `cf_starting_point` in the rulebook is what reports a filing that prints both.
    opbwc = calc(f"{op}__operating_profit_before_working_capital_changes",
                 "Operating profit before working capital changes", "营运资金变动前经营利润", "sum",
                 [n["canonical_key"] for n in adj], "subtotal")

    wc = [line(op, k, en, zh) for k, en, zh in CF_WORKING_CAPITAL]
    cgo = calc(f"{op}__cash_generated_from_operations", "Cash generated from operations",
               "经营活动产生的现金", "sum",
               [opbwc["canonical_key"], *(n["canonical_key"] for n in wc)], "subtotal")

    tail = [line(op, k, en, zh) for k, en, zh in CF_OPERATING_TAIL]
    ncfo = calc(f"{op}__net_cash_from_operating_activities", "Net cash from operating activities",
                "经营活动产生的现金流量净额", "sum",
                [cgo["canonical_key"], *(n["canonical_key"] for n in tail)], "subtotal")

    inv_lines = [line(inv, k, en, zh) for k, en, zh in CF_INVESTING]
    ncui = calc(f"{inv}__net_cash_used_in_investing_activities",
                "Net cash used in investing activities", "投资活动所用现金流量净额", "sum",
                [n["canonical_key"] for n in inv_lines], "subtotal")

    fin_lines = [line(fin, k, en, zh) for k, en, zh in CF_FINANCING]
    ncff = calc(f"{fin}__net_cash_from_financing_activities", "Net cash from financing activities",
                "筹资活动产生的现金流量净额", "sum",
                [n["canonical_key"] for n in fin_lines], "subtotal")

    net_movement = calc("cf_net_increase_decrease_in_cash_and_cash_equivalents",
                        "Net increase/(decrease) in cash and cash equivalents",
                        "现金及现金等价物增加/（减少）净额", "sum",
                        [ncfo["canonical_key"], ncui["canonical_key"], ncff["canonical_key"]],
                        "total")
    opening = {"node_id": "cf_opening_cash_and_cash_equivalents",
               "canonical_key": "cf_opening_cash_and_cash_equivalents",
               "label": "Opening cash and cash equivalents", "role": "total",
               "label_i18n": {"en": "Opening cash and cash equivalents", "zh": "期初现金及现金等价物"}}
    fx = {"node_id": "cf_effect_of_foreign_exchange_rate_changes",
          "canonical_key": "cf_effect_of_foreign_exchange_rate_changes",
          "label": "Effect of foreign exchange rate changes", "role": "line",
          "label_i18n": {"en": "Effect of foreign exchange rate changes", "zh": "汇率变动的影响"}}
    closing = calc("cf_closing_cash_and_cash_equivalents", "Closing cash and cash equivalents",
                   "期末现金及现金等价物", "sum",
                   [opening["canonical_key"], net_movement["canonical_key"],
                    fx["canonical_key"]], "total")

    return {
        "type": "cash_flow",
        "sections": [
            section("cf_s1_cash_flow_from_operating_activities",
                    "Cash flow from operating activities", "经营活动现金流量",
                    [*adj, opbwc, *wc, cgo, *tail, ncfo]),
            section("cf_s2_cash_flow_from_investing_activities",
                    "Cash flow from investing activities", "投资活动现金流量",
                    [*inv_lines, ncui]),
            section("cf_s3_cash_flow_from_financing_activities",
                    "Cash flow from financing activities", "筹资活动现金流量",
                    [*fin_lines, ncff]),
            net_movement, opening, fx, closing,
        ],
        "identities": [],
    }


# --- the rulebooks -----------------------------------------------------------------------------
# One row per new concept. ``after`` names the concept it is inserted behind, so a re-run puts it
# back in the same place. ``v1_section`` is the phrase the v1 file's ``description`` uses; ``v2``
# carries only what the v2 file states and the v1 file does not.
NEW_CONCEPTS = [
    {
        "canonical_key": "pl_expenses__total_cost_of_sales",
        "label": "Total cost of sales",
        "after": "pl_expenses__purchases_of_stock_in_trade",
        "definition": ("The reported subtotal of cost of sales, where a filing prints one — cost of "
                       "goods sold together with purchases of stock-in-trade."),
        "value_scope": "not_applicable",
        "aliases": ["Total cost of sales", "Total cost of goods sold", "Total cost of revenue",
                    "Total cost of sales and services"],
        "aliases_zh": ["销售成本总额", "销售成本合计", "营业成本合计"],
        "exclude": ["Cost of sales alone, which is its own concept.",
                    "Total operating cost, which also contains the operating expenses."],
        "confusable_with": ["pl_expenses__cost_of_goods_sold",
                            "pl_expenses__total_operating_cost"],
        "rulebook": {"inherits": "pl_s2_expenses", "match_priority": 76, "unit_of_account": "subtotal",
               "extraction_mode": "extract_or_derive", "sign_convention": "negative_expected",
               "derivation": ("sum of pl_expenses__cost_of_goods_sold and "
                              "pl_expenses__purchases_of_stock_in_trade where no subtotal is "
                              "printed")},
    },
    {
        "canonical_key": "pl_expenses__taxes_and_surcharges",
        "label": "Taxes and surcharges",
        "after": "pl_expenses__cost_of_goods_sold",
        "definition": ("Turnover-based taxes and levies charged as an operating expense — city "
                       "construction and maintenance tax, education surcharge, stamp duty, land "
                       "use and property tax. NOT income tax, which is struck below profit "
                       "before tax."),
        "value_scope": "exclusive_leaf",
        "aliases": ["Taxes and surcharges", "Taxes and levies", "Business taxes and surcharges",
                    "Taxes other than income tax"],
        "aliases_zh": ["税金及附加", "稅金及附加", "营业税金及附加", "營業稅金及附加"],
        "exclude": ["Income tax expense, current tax and deferred tax, which are a separate "
                    "section of the statement.",
                    "Value added tax recovered from customers, which is not an expense."],
        "confusable_with": ["pl_tax_expense__current_tax", "pl_tax_expense__total_tax_expense"],
        "exclude_hints": ["income tax", "所得税", "所得稅", "deferred"],
        "rulebook": {"inherits": "pl_s2_expenses", "match_priority": 66},
    },
    {
        "canonical_key": "pl_expenses__total_operating_expenses",
        "label": "Total operating expenses",
        "after": "pl_expenses__others",
        "definition": ("The reported subtotal of the operating expenses that sit below cost of "
                       "sales, where a filing prints one."),
        "value_scope": "not_applicable",
        "aliases": ["Total operating expenses", "Total operating expenditure",
                    "Total other operating expenses"],
        "aliases_zh": ["营业费用总额", "营业费用合计", "经营费用合计"],
        "exclude": ["Total operating cost, which also contains cost of sales.",
                    "Cost of sales and its own subtotal."],
        "confusable_with": ["pl_expenses__total_operating_cost",
                            "pl_expenses__total_cost_of_sales"],
        "rulebook": {"inherits": "pl_s2_expenses", "match_priority": 76, "unit_of_account": "subtotal",
               "extraction_mode": "extract_or_derive", "sign_convention": "negative_expected",
               "derivation": ("sum of the operating expense lines and pl_expenses__others where no "
                              "subtotal is printed")},
    },
    {
        "canonical_key": "pl_oci__items_not_reclassified",
        "label": "Items that will not be reclassified to profit or loss",
        "after": "pl_tax_expense__total_tax_expense",
        "definition": ("The IAS 1.82A(a) category of other comprehensive income: items that will "
                       "never be recycled through profit or loss. Where a filing itemises the "
                       "category rather than printing its subtotal, the itemised lines belong to "
                       "this concept and are summed into it."),
        "value_scope": "exclusive_leaf",
        "aliases": [
            "Items that will not be reclassified to profit or loss",
            "Item that will not be reclassified to profit or loss",
            "Items that will not be reclassified subsequently to profit or loss",
            "Will not be reclassified to profit or loss",
            "Fair value changes on equity investments at fair value through other comprehensive "
            "income",
            "Changes in fair value of equity investments at fair value through other comprehensive "
            "income",
            "Remeasurement of defined benefit obligations",
            "Remeasurement gains/(losses) on defined benefit plans",
            "Revaluation of property, plant and equipment",
        ],
        "aliases_zh": ["不会重分类进损益的项目", "不會重新分類至損益的項目", "以后不能重分类进损益的项目",
                       "以公允价值计量且其变动计入其他综合收益的权益工具投资公允价值变动",
                       "重新计量设定受益计划"],
        "exclude": ["The other comprehensive income subtotal for the year, which is its own "
                    "concept.",
                    "Items that MAY be reclassified subsequently to profit or loss, which are the "
                    "other category.",
                    "Amounts presented in profit or loss."],
        "confusable_with": ["pl_oci__items_may_be_reclassified",
                            "pl_other_comprehensive_income_for_the_year"],
        "rulebook": {"inherits": "pl_s8_other_comprehensive_income", "match_priority": 66},
    },
    {
        "canonical_key": "pl_oci__items_may_be_reclassified",
        "label": "Items that may be reclassified subsequently to profit or loss",
        "after": "pl_oci__items_not_reclassified",
        "definition": ("The IAS 1.82A(b) category of other comprehensive income: items that will "
                       "be recycled through profit or loss when the underlying position is "
                       "realised. Where a filing itemises the category rather than printing its "
                       "subtotal, the itemised lines belong to this concept and are summed into "
                       "it."),
        "value_scope": "exclusive_leaf",
        "aliases": [
            "Items that may be reclassified subsequently to profit or loss",
            "Item that may be reclassified subsequently to profit or loss",
            "Items that may be reclassified to profit or loss",
            "May be reclassified subsequently to profit or loss",
            "Exchange differences on translation of foreign operations",
            "Exchange differences on translating foreign operations",
            "Cash flow hedges",
            "Share of other comprehensive income of associates and joint ventures",
        ],
        "aliases_zh": ["将重分类进损益的项目", "可能重新分類至損益的項目", "以后可能重分类进损益的项目",
                       "换算境外业务产生的汇兑差额", "現金流量對沖", "应占联营及合营企业的其他综合收益"],
        "exclude": ["The other comprehensive income subtotal for the year, which is its own "
                    "concept.",
                    "Items that will NOT be reclassified to profit or loss, which are the other "
                    "category.",
                    "The effect of foreign exchange rate changes on cash, which is a cash-flow "
                    "reconciling item and not an OCI amount."],
        "confusable_with": ["pl_oci__items_not_reclassified",
                            "pl_other_comprehensive_income_for_the_year",
                            "cf_effect_of_foreign_exchange_rate_changes"],
        "rulebook": {"inherits": "pl_s8_other_comprehensive_income", "match_priority": 66},
    },
    {
        "canonical_key": "pl_oci__others",
        "label": "Other comprehensive income items (face, unmapped)",
        "after": "pl_oci__items_may_be_reclassified",
        "definition": ("Sweep bucket for value rows printed on the face of the statement of profit "
                       "or loss inside the other-comprehensive-income section that neither IAS 1 "
                       "category claimed. Governed entirely by residual_framework."),
        "value_scope": "exclusive_residual",
        "aliases": [],
        "aliases_zh": [],
        "exclude": [],
        "rulebook": {
            "inherits": "pl_s8_other_comprehensive_income",
            "alias_matching": "disabled",
            "match_priority": 0,
            "sign_convention": "either",
            "residual_policy": {
                "framework": "residual_framework",
                "section_scope": "pl_s8_other_comprehensive_income",
                "population": "sweep_only",
                "cross_section": False,
                "notes_as_source": False,
                "plug": False,
                "itemise": True,
            },
            "never_sweep": [
                "pl_other_comprehensive_income_for_the_year",
                "pl_total_comprehensive_income_for_the_year",
                "any row printed in the income, expenses, non-operating, exceptional or tax "
                "sections",
                "the total comprehensive income attribution captions",
            ],
            "expected_components": [
                "Exchange differences on translation of foreign operations, where the filing "
                "prints them without an IAS 1 category heading",
                "Movements in a hedging or revaluation reserve presented as their own face line",
                "Share of other comprehensive income of associates and joint ventures",
            ],
        },
    },
    {
        "canonical_key": "cf_cash_flow_from_operating_activities__profit_for_the_year",
        "label": "Profit for the year",
        "after": "cf_cash_flow_from_operating_activities__profit_before_tax",
        "definition": ("The starting line of an indirect-method cash flow that begins AFTER tax. "
                       "A statement starts from this line or from profit before tax, never both."),
        "value_scope": "exclusive_leaf",
        "aliases": ["Profit for the year", "Profit/(loss) for the year", "Loss for the year",
                    "Net profit for the year", "Profit for the period"],
        "aliases_zh": ["年度利润", "年度溢利", "年内利润", "本年净利润", "期间利润"],
        "exclude": ["The profit-or-loss line of the same name, which is a different statement.",
                    "Profit before tax, which is the other starting line."],
        "confusable_with": ["cf_cash_flow_from_operating_activities__profit_before_tax",
                            "pl_profit_for_the_year"],
        "rulebook": {"inherits": "cf_s1_operating", "match_priority": 70},
    },
    {
        "canonical_key": "cf_cash_flow_from_operating_activities__other_non_cash_adjustments",
        "label": "Other non-cash adjustments",
        "after": ("cf_cash_flow_from_operating_activities__"
                  "loss_gain_on_disposal_of_property_plant_and_equipment"),
        "definition": ("A printed catch-all for the non-cash adjustments a filing does not itemise, "
                       "struck before the working-capital movements."),
        "value_scope": "exclusive_leaf",
        "aliases": ["Other non-cash adjustments", "Other non-cash items",
                    "Other adjustments for non-cash items", "Other non-cash expenses"],
        "aliases_zh": ["其他非现金调整", "其他非現金調整", "其他非现金项目"],
        "exclude": ["Working capital movements, which are struck after this subtotal.",
                    "A specific adjustment this section maps as its own concept."],
        "rulebook": {"inherits": "cf_s1_operating", "match_priority": 55},
    },
    {
        "canonical_key": ("cf_cash_flow_from_operating_activities__"
                          "operating_profit_before_working_capital_changes"),
        "label": "Operating profit before working capital changes",
        "after": "cf_cash_flow_from_operating_activities__other_non_cash_adjustments",
        "definition": ("The HKAS 7 indirect-method subtotal struck after the non-cash adjustments "
                       "and before the working-capital movements."),
        "value_scope": "not_applicable",
        "aliases": ["Operating profit before working capital changes",
                    "Operating cash flows before movements in working capital",
                    "Operating profit before changes in working capital",
                    "Cash flows from operations before movements in working capital"],
        "aliases_zh": ["营运资金变动前经营利润", "營運資金變動前經營利潤", "经营资金变动前的营业利润",
                       "营运资金变动前经营现金流量"],
        "exclude": ["Cash generated from operations, which is struck after the working-capital "
                    "movements.",
                    "Net cash from operating activities."],
        "confusable_with": ["cf_cash_flow_from_operating_activities__cash_generated_from_operations",
                            ("cf_cash_flow_from_operating_activities__"
                             "net_cash_from_operating_activities")],
        "rulebook": {"inherits": "cf_s1_operating", "match_priority": 76, "unit_of_account": "subtotal",
               "extraction_mode": "extract_or_derive",
               "derivation": ("sum of the starting line and the non-cash adjustments where no "
                              "subtotal is printed")},
    },
    {
        "canonical_key": "cf_cash_flow_from_operating_activities__other_working_capital_movements",
        "label": "Other working capital movements",
        "after": ("cf_cash_flow_from_operating_activities__"
                  "increase_decrease_in_other_payables_and_accruals"),
        "definition": ("A printed catch-all for the working-capital movements a filing does not "
                       "itemise, struck before cash generated from operations."),
        "value_scope": "exclusive_leaf",
        "aliases": ["Other working capital movements", "Other changes in working capital",
                    "Other movements in working capital", "Changes in other working capital"],
        "aliases_zh": ["其他营运资金变动", "其他營運資金變動", "其他经营性应收应付项目的变动"],
        "exclude": ["A specific working-capital movement this section maps as its own concept.",
                    "Non-cash adjustments, which are struck before this block."],
        "rulebook": {"inherits": "cf_s1_operating", "match_priority": 55},
    },
    {
        "canonical_key": "cf_cash_flow_from_operating_activities__interest_paid",
        "label": "Interest paid",
        "after": "cf_cash_flow_from_operating_activities__interest_received",
        "definition": ("Interest paid classified as an operating cash flow, which HKAS 7.33 "
                       "permits. The same caption in the financing section is a different concept "
                       "and only one of the two is populated."),
        "value_scope": "exclusive_leaf",
        "aliases": ["Interest paid", "Interest paid on bank and other borrowings",
                    "Interest and finance charges paid"],
        "aliases_zh": ["已付利息", "已付利息费用", "支付的利息"],
        "exclude": ["Interest paid presented in the financing section, which is its own concept.",
                    "Finance costs recognised in profit or loss, which are an add-back above.",
                    "Interest received."],
        "confusable_with": ["cf_cash_flow_from_financing_activities__interest_paid",
                            "cf_cash_flow_from_operating_activities__finance_costs"],
        "rulebook": {"inherits": "cf_s1_operating", "match_priority": 66,
               "sign_convention": "negative_expected"},
    },
    {
        "canonical_key": "cf_cash_flow_from_investing_activities__advances_to_related_parties",
        "label": "Advances to related parties",
        "after": "cf_cash_flow_from_investing_activities__disposal_of_subsidiaries_net_of_cash_disposed",
        "definition": ("Loans and advances made to related parties, and repayments received on "
                       "them, presented as an investing cash flow."),
        "value_scope": "exclusive_leaf",
        "aliases": ["Advances to related parties", "Loans to related parties",
                    "Advances to associates and joint ventures",
                    "(Advances to)/repayments from related parties",
                    "Amounts advanced to related parties"],
        "aliases_zh": ["向关联方提供的款项", "向關聯方提供的款項", "向关联方垫款", "应收关联方款项变动"],
        "exclude": ["Advances FROM related parties, which are a financing cash flow and their own "
                    "concept.",
                    "Trade balances with related parties, which are a working-capital movement."],
        "confusable_with": ["cf_cash_flow_from_financing_activities__advances_from_related_parties"],
        "rulebook": {"inherits": "cf_s2_investing", "match_priority": 66},
    },
    {
        "canonical_key": "cf_cash_flow_from_financing_activities__advances_from_related_parties",
        "label": "Advances from related parties",
        "after": "cf_cash_flow_from_financing_activities__capital_contributions_from_non_controlling_interests",
        "definition": ("Loans and advances received from related parties, and repayments made on "
                       "them, presented as a financing cash flow."),
        "value_scope": "exclusive_leaf",
        "aliases": ["Advances from related parties", "Loans from related parties",
                    "Advances from a shareholder", "Advances from the immediate holding company",
                    "Amounts advanced from related parties"],
        "aliases_zh": ["关联方提供的款项", "關聯方提供的款項", "关联方垫款", "应付关联方款项变动"],
        "exclude": ["Advances TO related parties, which are an investing cash flow and their own "
                    "concept.",
                    "Trade balances with related parties, which are a working-capital movement."],
        "confusable_with": ["cf_cash_flow_from_investing_activities__advances_to_related_parties"],
        "rulebook": {"inherits": "cf_s3_financing", "match_priority": 66},
    },
]

# Sign expectations the spec states for lines that already exist. An add-back reverses a charge in
# profit or loss, so it is positive by construction; interest income is deducted, so it is
# negative. v1 states no ``sign_convention`` on any concept and is left alone.
SIGN_CONVENTIONS = {
    "cf_cash_flow_from_operating_activities__income_tax_expense": "positive_expected",
    "cf_cash_flow_from_operating_activities__depreciation_and_amortisation": "positive_expected",
    "cf_cash_flow_from_operating_activities__finance_costs": "positive_expected",
    "cf_cash_flow_from_operating_activities__impairment_losses_on_financial_and_contract_assets":
        "positive_expected",
    "cf_cash_flow_from_operating_activities__interest_income": "negative_expected",
}

# The section layer gains one entry. Cost of sales deliberately does NOT get one: the matching gate
# reads a section token off the end of a scope id (``mapping.section_token_of_scope``) and there is
# no banner vocabulary for cost of sales, so a scope id naming it would resolve to nothing and leave
# those concepts LESS constrained than they are today under ``pl_s2_expenses``. Cost of sales is an
# expense; the template presents it separately, the rulebook recognises it as one.
NEW_SECTION_DEFAULTS = {
    "pl_s8_other_comprehensive_income": {
        "statement": "profit_and_loss",
        "section_scope": ["pl_s8_other_comprehensive_income"],
        "temporality": "duration",
        "unit_of_account": "flow",
        "value_scope": "exclusive_leaf",
        "extraction_mode": "extract",
        "face_only": True,
        "note_use": "evidence_only",
        "sign_convention": "either",
        "match_priority": 50,
        "include": [
            "The face amount for the selected entity_scope, period, currency and unit, retaining "
            "the reported sign.",
        ],
        "exclude": [
            "Amounts presented in profit or loss above the profit-for-the-year line.",
            "The total comprehensive income attribution captions, which are their own section.",
            "Section subtotals and statement totals.",
        ],
    },
}

# Groups a filing must populate one side of, never both.
NEW_EXCLUSIVE_GROUPS = [
    {
        "id": "cf_starting_point",
        "note": ("The template's operating rollup lists both starting lines because exactly one is "
                 "ever printed, which is how the spec's COALESCE is expressed without a COALESCE "
                 "operator. A filing populating both would count its profit twice in operating "
                 "profit before working capital changes."),
        "aggregate": "cf_cash_flow_from_operating_activities__profit_before_tax",
        "components": ["cf_cash_flow_from_operating_activities__profit_for_the_year"],
        "rule": ("An indirect-method cash flow starts from profit before tax OR from profit for the "
                 "year. Populate whichever the face prints and leave the other null."),
    },
    {
        "id": "oci_composition",
        "note": ("The template's pl_other_comprehensive_income_for_the_year rollup lists both "
                 "categories. Loading the printed subtotal alongside them double-counts other "
                 "comprehensive income, and the rollup reports the disagreement when a filing "
                 "prints both."),
        "aggregate": "pl_other_comprehensive_income_for_the_year",
        "components": ["pl_oci__items_not_reclassified", "pl_oci__items_may_be_reclassified"],
        "rule": ("Populate the subtotal only when the face prints a single undifferentiated other "
                 "comprehensive income line. If either category is printed, populate the "
                 "categories and leave the subtotal null."),
    },
]

# Relations the revision authors in the rulebook, each in ONE place. The cross-statement ties cannot
# be template identities (those are per statement), which is why they live here.
NEW_IDENTITIES = [
    {"id": "cf_pfy_agreement",
     "expr": ("cf_cash_flow_from_operating_activities__profit_for_the_year = "
              "pl_profit_for_the_year"),
     "severity": "blocking",
     "note": ("The other half of the spec's COALESCE_MATCHED: this pairs with cf_pbt_agreement, and "
              "because a cash flow starts from one line or the other, exactly one of the two ever "
              "has both operands and runs. Comparing the cash flow's starting profit against the "
              "WRONG P&L line would fail by the tax charge on every correct filing.")},
    {"id": "pl_oci_composition",
     "expr": ("pl_other_comprehensive_income_for_the_year = pl_oci__items_not_reclassified "
              "+ pl_oci__items_may_be_reclassified"),
     "severity": "warning",
     "note": ("Restates the new rollup so the composition carries the spec's severity: a filing "
              "whose two IAS 1 categories disagree with the printed subtotal has a classification "
              "difference worth a look, not a broken statement. Skips when either side is absent.")},
    {"id": "x_check_tax",
     "expr": ("cf_cash_flow_from_operating_activities__income_tax_expense = "
              "-pl_tax_expense__total_tax_expense"),
     "severity": "warning",
     "note": ("The tax charge added back in the cash flow is the tax charge in profit or loss, "
              "with the sign reversed because expenses are stored negative. Skips on a cash flow "
              "that starts after tax, where there is no add-back to compare.")},
    {"id": "x_check_dep",
     "expr": ("cf_cash_flow_from_operating_activities__depreciation_and_amortisation = "
              "-pl_expenses__depreciation_and_amortisation_expense"),
     "severity": "warning",
     "note": ("Depreciation and amortisation added back in the cash flow against the charge in "
              "profit or loss. The spec asks for a 0.5% tolerance, which an identity cannot carry, "
              "so this runs on the shared tolerance: a small break here is usually depreciation "
              "capitalised into inventory or a development asset rather than an extraction error.")},
    {"id": "x_check_interest",
     "expr": ("cf_cash_flow_from_operating_activities__finance_costs = "
              "-pl_non_operating_expenses__interest_expense"),
     "severity": "warning",
     "note": ("Finance costs added back in the cash flow against interest expense in profit or "
              "loss. The spec marks this advisory with a 2% tolerance; the severity enum has no "
              "advisory level and an identity carries no tolerance, so it is a warning — "
              "capitalised interest causes a legitimate variance and a break here is a question, "
              "not a defect.")},
]

# Identities whose expression the revision retargets, with the reason.
IDENTITY_EXPRESSIONS = {
    # Gross profit now routes through the cost-of-sales subtotal in the template. This one stays on
    # the LEAVES and gains the purchases term, so it keeps running on a filing that prints no
    # cost-of-sales subtotal — which is most of them — and is CORRECT on one that splits the cost.
    # Without the purchases term it fails by exactly that line on any filing that prints it.
    "pl_gross_profit_tie": ("pl_gross_profit = pl_income__revenue_from_operations "
                            "+ pl_expenses__cost_of_goods_sold "
                            "+ pl_expenses__purchases_of_stock_in_trade"),
    # The FX effect is no longer a section key.
    "cf_closing": ("cf_closing_cash_and_cash_equivalents = cf_opening_cash_and_cash_equivalents "
                   "+ cf_net_increase_decrease_in_cash_and_cash_equivalents "
                   "+ cf_effect_of_foreign_exchange_rate_changes"),
}

# Severities the spec raises. Both were authored as "worth a look" and the spec calls them failures.
SEVERITY_CHANGES = {
    # The cash flow's starting profit and the P&L's profit before tax are the same figure printed
    # twice. A disagreement is a mis-extraction on one of the two statements, not a presentation
    # difference.
    "cf_pbt_agreement": "blocking",
    # Closing cash against balance-sheet cash. Raised as the spec asks; note that a filing which
    # nets bank overdrafts into cash equivalents will now raise a blocking card, which is the
    # trade-off of making this a failure.
    "cf_to_bs_cash": "blocking",
}


def _concept(spec: dict) -> dict:
    """One new concept.

    A single shape, because a single rulebook ships. This took a ``v2`` flag while two generations
    did, and each concept had to be written twice — once with ``inherits``/``match_priority`` and
    once with ``description``/``extraction_mode``/``include`` — with nothing but an invariant test
    to catch a concept written in the wrong one. It caught two.
    """
    aliases = list(spec["aliases"])
    entry = {"canonical_key": spec["canonical_key"], "label": spec["label"],
             "definition": spec["definition"], **spec["rulebook"],
             "value_scope": spec["value_scope"]}
    entry["aliases"] = aliases
    entry["aliases_i18n"] = {"en": aliases, "zh": list(spec["aliases_zh"])}
    if spec["exclude"]:
        entry["exclude"] = list(spec["exclude"])
    if spec.get("confusable_with"):
        entry["confusable_with"] = list(spec["confusable_with"])
    if spec.get("exclude_hints"):
        entry["exclude_hints"] = list(spec["exclude_hints"])
    return entry


def seed_concepts(data: dict) -> list[str]:
    """Insert (or replace) each new concept behind the one it is printed after."""
    mappings = data.setdefault("mappings", [])
    notes: list[str] = []
    for spec in NEW_CONCEPTS:
        entry = _concept(spec)
        idx = _mapping_index(data)
        at = idx.get(entry["canonical_key"])
        if at is not None:
            if mappings[at] != entry:
                mappings[at] = entry
                notes.append(f"{entry['canonical_key']} rewritten to this file's shape")
            continue
        after = idx.get(spec["after"])
        mappings.insert(len(mappings) if after is None else after + 1, entry)
        notes.append(f"{entry['canonical_key']} seeded")
    return notes


def drop_concepts(data: dict) -> list[str]:
    """Delete a retired concept and every reference to it.

    The references are the point. ``pl_total_expenses`` was named from a ``never_sweep`` list and a
    ``confusable_with`` list; deleting only the mapping would leave two entries pointing at a
    concept that no longer exists — and ``confusable_with`` drives the collision families, so the
    dangling name silently shrinks a family rather than failing.
    """
    notes: list[str] = []
    mappings = data.get("mappings") or []
    for key in sorted(DROP_CONCEPTS):
        before = len(mappings)
        data["mappings"] = mappings = [m for m in mappings if m.get("canonical_key") != key]
        if len(mappings) < before:
            notes.append(f"{key} deleted")
        refs = _strip_references(data, key)
        if refs:
            notes.append(f"{refs} reference(s) to {key} removed")
    return notes


def _strip_references(node, key: str) -> int:
    """Remove ``key`` from every list of canonical keys it appears in, in place."""
    removed = 0
    if isinstance(node, dict):
        for field, value in node.items():
            if isinstance(value, list) and key in value and field != "mappings":
                removed += value.count(key)
                node[field] = [v for v in value if v != key]
            else:
                removed += _strip_references(value, key)
    elif isinstance(node, list):
        for value in node:
            removed += _strip_references(value, key)
    return removed


def apply_key_fixes(data: dict) -> tuple[dict, int]:
    """Rename the two corrected keys everywhere they are written, outside ``metadata``.

    A whole-document walk, for the reason ``_rename_everywhere`` records: both keys are named from
    places that are not a ``canonical_key`` field — two ``derivation`` sentences, a ``never_sweep``
    entry, one ``validation`` expression — and renaming only the field they define leaves the rest
    pointing at a key that no longer exists. ``metadata`` is held back, and
    ``rename_outside_metadata`` records why: the breaking-change note names both spellings on
    purpose.
    """
    return rename_outside_metadata(data, KEY_FIXES)


def drop_template_note(data: dict) -> str | None:
    """Delete the ``template_note`` that asked for the defect this revision fixes.

    The v2 entry for the FX concept carried: "The template declares this node with role: header and
    an empty children array, yet uses it as a value input … the template node role should be
    corrected to 'line'." It now is, and a note describing a fixed defect is prose a reader trusts.
    """
    for m in data.get("mappings") or []:
        if m.get("canonical_key") != "cf_effect_of_foreign_exchange_rate_changes":
            continue
        if "template_note" in m:
            del m["template_note"]
            return "the FX concept's template_note is deleted (the template node is now a line)"
    return None


def add_section_defaults(data: dict) -> list[str]:
    sections = data.get("section_defaults")
    if not isinstance(sections, dict):
        return []                        # v1 declares no section layer; that is its shape
    notes = []
    for sid, body in NEW_SECTION_DEFAULTS.items():
        if sections.get(sid) != body:
            sections[sid] = body
            notes.append(f"section_defaults gains {sid}")
    return notes


def add_exclusive_groups(data: dict) -> list[str]:
    rules = data.get("global_rules")
    if not isinstance(rules, dict) or "mutually_exclusive_groups" not in rules:
        return []
    groups = rules["mutually_exclusive_groups"]
    at = {g.get("id"): n for n, g in enumerate(groups)}
    notes = []
    for group in NEW_EXCLUSIVE_GROUPS:
        if group["id"] in at:
            if groups[at[group["id"]]] != group:
                groups[at[group["id"]]] = group
                notes.append(f"exclusivity group {group['id']} updated")
        else:
            groups.append(group)
            notes.append(f"exclusivity group {group['id']} added")
    return notes


def apply_sign_conventions(data: dict) -> list[str]:
    """State the spec's sign expectations, in the file that has a field for them."""
    if not any("sign_convention" in m for m in data.get("mappings") or []):
        return []                        # v1 states none; adding one here invents its vocabulary
    notes = []
    for m in data.get("mappings") or []:
        want = SIGN_CONVENTIONS.get(m.get("canonical_key"))
        if want and m.get("sign_convention") != want:
            m["sign_convention"] = want
            notes.append(f"{m['canonical_key']} is {want}")
    return notes



def sync_residual_count(data: dict) -> str | None:
    """Hold ``residual_framework.note``'s count to the number of residuals actually declared.

    The sentence reads "One definition governing all N residual concepts", and it is served on the
    ontology screen. Adding the other-comprehensive-income bucket makes N wrong, and a block whose
    own first sentence miscounts what it governs is the same defect class as ``metadata.concept_count``
    disagreeing with the mappings — a number nobody derived from what it sits above.
    """
    framework = data.get("residual_framework")
    if not isinstance(framework, dict) or not isinstance(framework.get("note"), str):
        return None
    actual = sum(1 for m in data.get("mappings") or []
                 if isinstance(m.get("residual_policy"), dict))
    note = re.sub(r"all \d+ residual concepts", f"all {actual} residual concepts",
                  framework["note"])
    if note == framework["note"]:
        return None
    framework["note"] = note
    return f"residual_framework.note now says {actual} residual concepts"


def revise_validation(data: dict) -> list[str]:
    rules = data.get("validation")
    if not isinstance(rules, dict) or "identities" not in rules:
        return []                        # v1 declares no validation block; that is its shape
    idents = rules["identities"]
    notes = []
    at = {i.get("id"): n for n, i in enumerate(idents)}
    for ident in NEW_IDENTITIES:
        if ident["id"] in at:
            if idents[at[ident["id"]]] != ident:
                idents[at[ident["id"]]] = ident
                notes.append(f"identity {ident['id']} updated")
        else:
            idents.append(ident)
            notes.append(f"identity {ident['id']} added")
    at = {i.get("id"): n for n, i in enumerate(idents)}
    for rid, expr in IDENTITY_EXPRESSIONS.items():
        if rid in at and idents[at[rid]].get("expr") != expr:
            idents[at[rid]]["expr"] = expr
            notes.append(f"identity {rid} retargeted")
    for rid, severity in SEVERITY_CHANGES.items():
        if rid in at and idents[at[rid]].get("severity") != severity:
            idents[at[rid]]["severity"] = severity
            notes.append(f"identity {rid} raised to {severity}")
    return notes


def revise_ontologies() -> list[str]:
    out: list[str] = []
    for path in (ONTOLOGY,):
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        notes: list[str] = []
        data, renamed = apply_key_fixes(data)
        if renamed:
            notes.append(f"{renamed} key(s) renamed everywhere they are written")
        notes += drop_concepts(data)
        notes += seed_concepts(data)
        if dropped := drop_template_note(data):
            notes.append(dropped)
        notes += add_section_defaults(data)
        notes += add_exclusive_groups(data)
        notes += apply_sign_conventions(data)
        if counted := sync_declared_count(data):
            notes.append(counted)
        if swept := sync_residual_count(data):
            notes.append(swept)
        notes += revise_validation(data)
        if notes:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            out += [f"{path.name}: {n}" for n in notes]
    return out


def _rows(statement: dict) -> int:
    return sum(1 + len(s.get("children") or []) if s.get("children") else 1
               for s in statement["sections"])


def main() -> int:
    tpl = json.loads(TPL.read_text())
    built = {"profit_and_loss": build_profit_and_loss(), "cash_flow": build_cash_flow()}
    seen = set()
    for i, st in enumerate(tpl["statements"]):
        if st.get("type") in built:
            tpl["statements"][i] = built[st["type"]]
            seen.add(st["type"])
    missing = sorted(set(built) - seen)
    if missing:
        print(f"no {', '.join(missing)} statement(s) to replace")
        return 1
    TPL.write_text(json.dumps(tpl, ensure_ascii=False, indent=2) + "\n")
    for name, statement in built.items():
        print(f"{name} rewritten: {len(statement['sections'])} top-level nodes, "
              f"{_rows(statement)} screen rows")
    for note in revise_ontologies():
        print(f"  {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

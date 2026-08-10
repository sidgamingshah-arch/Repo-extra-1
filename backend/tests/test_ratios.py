"""Credit-focused ratio catalog — computed strictly from extracted canonical values.

Golden values are asserted at the ``compute_ratios`` altitude (synthetic rows) so the test
is independent of the extractor's label→key mapping."""
from __future__ import annotations

from app.services.derived import compute_ratios


def _row(key, cur, prior=None):
    vals = [{"basis": "consolidated", "period_label": "current", "value": str(cur)}]
    if prior is not None:
        vals.append({"basis": "consolidated", "period_label": "prior", "value": str(prior)})
    return {"canonical_key": key, "values": vals}


def _credit_rows():
    return [
        _row("bs_current_assets__total_current_assets", 6614),
        _row("bs_current_assets__inventories", 2000),
        _row("bs_current_assets__trade_receivables", 3410),
        _row("bs_current_assets__cash_and_cash_equivalents", 1204),
        _row("bs_current_liabilities__total_current_liabilities", 3300),
        _row("bs_current_liabilities__current_borrowings", 800),
        _row("bs_current_liabilities__current_potion_of_long_term_debt", 200),
        _row("bs_current_liabilities__current_trade_payables", 1500),
        _row("bs_non_current_liabilities__total_non_current_liabilities", 4200),
        _row("bs_non_current_liabilities__non_current_borrowings", 3000),
        _row("bs_non_current_liabilities__non_current_bonds_payable", 1000),
        _row("bs_equity__total_equity", 9114),
        _row("bs_total_assets", 16614),
        _row("pl_income__revenue_from_operations", 20000),
        _row("pl_expenses__cost_of_goods_sold", 12000),
        _row("pl_operating_profit_ebit", 3200),
        _row("pl_expenses__depreciation_and_amortisation_expense", 800),
        _row("pl_non_operating_expenses__interest_expense", 400),
        _row("pl_profit_for_the_year", 2400),
        _row("cf_cash_flow_from_operating_activities__net_cash_from_operating_activities", 3500),
        _row("cf_cash_flow_from_investing_activities__purchase_of_property_plant_and_equipment", 1500),
        _row("cf_cash_flow_from_financing_activities__interest_paid", 380),
        _row("cf_cash_flow_from_financing_activities__repayment_of_borrowings", 600),
    ]


def test_credit_ratios_compute_expected_values():
    by_key = {r["key"]: r for r in compute_ratios(_credit_rows())}

    # Total debt = 800 + 200 + 3000 + 1000 = 5000; cash = 1204; equity = 9114; EBITDA = 3200 + 800.
    assert by_key["gross_gearing"]["value"] == round(5000 / 9114, 2)          # 0.55×
    assert by_key["net_gearing"]["value"] == round((5000 - 1204) / 9114, 2)   # 0.42×
    assert by_key["debt_to_capital"]["value"] == round(5000 / (5000 + 9114) * 100, 2)   # 35.43%
    assert by_key["debt_ratio"]["value"] == round((4200 + 3300) / 16614 * 100, 2)       # 45.14%
    assert by_key["debt_to_ebitda"]["value"] == round(5000 / 4000, 2)         # 1.25×
    assert by_key["net_debt_to_ebitda"]["value"] == round((5000 - 1204) / 4000, 2)      # 0.95×
    assert by_key["equity_multiplier"]["value"] == round(16614 / 9114, 2)

    # Coverage
    assert by_key["ebitda_interest_coverage"]["value"] == round(4000 / 400, 2)          # 10.0×
    assert by_key["debt_service_coverage"]["value"] == round(4000 / (400 + 200 + 800), 2)  # 2.86×
    assert by_key["cfo_to_total_debt"]["value"] == round(3500 / 5000 * 100, 2)          # 70.0%
    assert by_key["fcf_to_total_debt"]["value"] == round((3500 - 1500) / 5000 * 100, 2) # 40.0%
    # FFO = profit for the year + D&A = 2400 + 800; cash debt service = CFO / (interest paid + repayment).
    assert by_key["ffo_to_total_debt"]["value"] == round((2400 + 800) / 5000 * 100, 2)  # 64.0%
    assert by_key["cash_debt_service_coverage"]["value"] == round(3500 / (380 + 600), 2)

    # Profitability — EBITDA margin and ROCE (capital employed = assets − current liabilities).
    assert by_key["ebitda_margin"]["value"] == round(4000 / 20000 * 100, 2)             # 20.0%
    assert by_key["return_on_capital_employed"]["value"] == round(3200 / (16614 - 3300) * 100, 2)

    # Liquidity
    assert by_key["cash_ratio"]["value"] == round(1204 / 3300, 2)
    assert by_key["operating_cash_flow_ratio"]["value"] == round(3500 / 3300, 2)

    # Efficiency — day-based cycle, unit "days", and the derived cash conversion cycle.
    assert by_key["dso"]["unit"] == "days"
    assert by_key["dso"]["value"] == round(3410 / 20000 * 365, 2)
    assert by_key["dio"]["value"] == round(2000 / 12000 * 365, 2)
    assert by_key["dpo"]["value"] == round(1500 / 12000 * 365, 2)
    ccc = by_key["cash_conversion_cycle"]
    assert ccc["display"].endswith("days")
    assert ccc["value"] == round(by_key["dso"]["value"] + by_key["dio"]["value"]
                                 - by_key["dpo"]["value"], 2)


def test_total_debt_aggregates_present_components_only():
    """'Total debt' sums whatever debt components are present (missing => 0); it does not
    require every component, but needs at least one."""
    rows = [_row("bs_equity__total_equity", 1000),
            _row("bs_non_current_liabilities__non_current_borrowings", 400)]
    g = {r["key"]: r for r in compute_ratios(rows)}["gross_gearing"]
    assert g["available"] and g["value"] == round(400 / 1000, 2)   # only one debt component present

    # No debt components at all → the aggregate has nothing to measure → unavailable.
    g2 = {r["key"]: r for r in compute_ratios([_row("bs_equity__total_equity", 1000)])}["gross_gearing"]
    assert not g2["available"] and g2["display"] == "—"


def test_dio_dpo_fall_back_to_total_operating_cost_when_cogs_absent():
    """DIO/DPO prefer the explicit COGS line, but fall back to total operating cost when a
    filing doesn't break out COGS — so the day-cycle still computes."""
    base = [_row("bs_current_assets__inventories", 2000),
            _row("bs_current_liabilities__current_trade_payables", 1500)]

    # COGS present → used directly.
    with_cogs = {r["key"]: r for r in compute_ratios(
        base + [_row("pl_expenses__cost_of_goods_sold", 12000),
                _row("pl_expenses__total_operating_cost", 15000)])}
    assert with_cogs["dio"]["value"] == round(2000 / 12000 * 365, 2)
    assert with_cogs["dpo"]["value"] == round(1500 / 12000 * 365, 2)

    # COGS absent → fall back to total operating cost (15000).
    no_cogs = {r["key"]: r for r in compute_ratios(
        base + [_row("pl_expenses__total_operating_cost", 15000)])}
    assert no_cogs["dio"]["available"] and no_cogs["dio"]["value"] == round(2000 / 15000 * 365, 2)
    assert no_cogs["dpo"]["available"] and no_cogs["dpo"]["value"] == round(1500 / 15000 * 365, 2)

    # Neither present → genuinely unavailable (never fabricated).
    neither = {r["key"]: r for r in compute_ratios(base)}
    assert not neither["dio"]["available"] and not neither["dpo"]["available"]


def test_ratios_grouped_by_category_credit_first():
    cats = [r["category"] for r in compute_ratios(_credit_rows())]
    # Categories appear as contiguous blocks, credit-relevant ones first.
    seen = [c for i, c in enumerate(cats) if i == 0 or cats[i - 1] != c]
    assert seen == ["Liquidity", "Leverage", "Coverage", "Efficiency", "Profitability"]
    assert {"gross_gearing", "net_debt_to_ebitda", "debt_service_coverage"} <= {
        r["key"] for r in compute_ratios(_credit_rows()) if r["category"] in ("Leverage", "Coverage")}


def test_credit_ratios_localized_labels():
    zh = {r["key"]: r for r in compute_ratios(_credit_rows(), locale="zh")}
    assert zh["net_debt_to_ebitda"]["label"] == "净债务/EBITDA"
    assert zh["dso"]["label"] == "应收账款周转天数"


def test_unavailable_ratios_never_fabricated():
    """With almost nothing extracted, credit ratios are returned but flagged unavailable —
    the full catalog is always visible, never invented."""
    out = compute_ratios([_row("bs_total_assets", 100)])
    assert out and all(not r["available"] or r["value"] is not None for r in out)
    assert any(not r["available"] for r in out)
    assert {"gross_gearing", "net_debt_to_ebitda", "cfo_to_total_debt"} <= {r["key"] for r in out}

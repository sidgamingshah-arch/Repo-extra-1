"""Derived analysis from a real extraction — all computed from the extracted values (never
fabricated):

1. Ratios     — standard financial ratios computed from canonical line-item values.
2. Disclosures— presence scan for qualitative items (auditor qualification, contingent
                liabilities, guarantees, …) with the page + snippet where found.
3. Free notes — plain-language notes generated from the extracted movements/ratios.

Ratios and notes are recomputed from the current rows (so edits/reverts are reflected);
disclosures come from a one-time text scan stored on the run.
"""
from __future__ import annotations

import re

# --- 1. Ratios -------------------------------------------------------------
# Each ratio references canonical keys; num/den are (key, sign) so we can net inventories
# out of the quick ratio etc. A ratio is computed only when ALL its inputs are present.
# Reusable component term-lists. Debt/cash components are "opt" — a company reports only some
# of them, and the aggregate should still compute from whatever is present.
_DEBT = [
    ("bs_non_current_liabilities__non_current_borrowings", 1, "opt"),
    ("bs_non_current_liabilities__non_current_bonds_payable", 1, "opt"),
    ("bs_non_current_liabilities__non_current_notes_payable", 1, "opt"),
    ("bs_non_current_liabilities__non_current_lease_liabilities", 1, "opt"),
    ("bs_current_liabilities__current_borrowings", 1, "opt"),
    ("bs_current_liabilities__current_potion_of_long_term_debt", 1, "opt"),
    ("bs_current_liabilities__cuurent_notes_payable", 1, "opt"),
    ("bs_current_liabilities__current_lease_liabilities", 1, "opt"),
]
_CASH = [
    ("bs_current_assets__cash_and_cash_equivalents", 1, "opt"),
    ("bs_current_assets__bank_balances_other_than_cash_and_cash_equivalents", 1, "opt"),
]
# EBITDA = EBIT (required anchor) + depreciation & amortisation (optional add-back).
_EBITDA = [("pl_operating_profit_ebit", 1), ("pl_expenses__depreciation_and_amortisation_expense", 1, "opt")]
_CFO = "cf_cash_flow_from_operating_activities__net_cash_from_operating_activities"
_CAPEX = "cf_cash_flow_from_investing_activities__purchase_of_property_plant_and_equipment"
_EQUITY = "bs_equity__total_equity"
_TCL = "bs_current_liabilities__total_current_liabilities"
_INTEREST = "pl_non_operating_expenses__interest_expense"

_RATIOS = [
    # ---- Liquidity -------------------------------------------------------------------
    {"key": "current_ratio", "label": "Current ratio", "unit": "x", "category": "Liquidity",
     "label_i18n": {"zh": "流动比率", "ar": "نسبة التداول", "fr": "Ratio de liquidité générale"},
     "num": [("bs_current_assets__total_current_assets", 1)],
     "den": [(_TCL, 1)],
     "formula": "Total current assets / Total current liabilities"},
    {"key": "quick_ratio", "label": "Quick ratio", "unit": "x", "category": "Liquidity",
     "label_i18n": {"zh": "速动比率", "ar": "نسبة السيولة السريعة", "fr": "Ratio de liquidité réduite"},
     "num": [("bs_current_assets__total_current_assets", 1), ("bs_current_assets__inventories", -1)],
     "den": [(_TCL, 1)],
     "formula": "(Total current assets − Inventories) / Total current liabilities"},
    {"key": "cash_ratio", "label": "Cash ratio", "unit": "x", "category": "Liquidity",
     "label_i18n": {"zh": "现金比率", "ar": "نسبة النقد", "fr": "Ratio de liquidité immédiate"},
     "num": list(_CASH), "den": [(_TCL, 1)],
     "formula": "(Cash + bank balances) / Total current liabilities"},
    {"key": "operating_cash_flow_ratio", "label": "Operating cash flow ratio", "unit": "x",
     "category": "Liquidity",
     "label_i18n": {"zh": "经营现金流比率", "ar": "نسبة التدفق النقدي التشغيلي",
                    "fr": "Ratio de flux de trésorerie d'exploitation"},
     "num": [(_CFO, 1)], "den": [(_TCL, 1)],
     "formula": "Net cash from operating activities / Total current liabilities"},

    # ---- Leverage --------------------------------------------------------------------
    {"key": "debt_to_equity", "label": "Liabilities to equity", "unit": "x", "category": "Leverage",
     "label_i18n": {"zh": "负债权益比", "ar": "نسبة الالتزامات إلى حقوق الملكية",
                    "fr": "Passif / Capitaux propres"},
     "num": [("bs_non_current_liabilities__total_non_current_liabilities", 1),
             (_TCL, 1)],
     "den": [(_EQUITY, 1)],
     "formula": "(Non-current + current liabilities) / Total equity"},
    {"key": "gross_gearing", "label": "Gross gearing (debt/equity)", "unit": "x", "category": "Leverage",
     "label_i18n": {"zh": "总杠杆（债务/权益）", "ar": "الرافعة الإجمالية (الدين/حقوق الملكية)",
                    "fr": "Endettement brut (dette/capitaux propres)"},
     "num": list(_DEBT), "den": [(_EQUITY, 1)],
     "formula": "Total debt / Total equity"},
    {"key": "net_gearing", "label": "Net gearing (net debt/equity)", "unit": "x", "category": "Leverage",
     "label_i18n": {"zh": "净杠杆（净债务/权益）", "ar": "صافي الرافعة (صافي الدين/حقوق الملكية)",
                    "fr": "Endettement net (dette nette/capitaux propres)"},
     "num": _DEBT + [(k, -1, "opt") for (k, _s, _m) in _CASH], "den": [(_EQUITY, 1)],
     "formula": "(Total debt − Cash) / Total equity"},
    {"key": "debt_to_capital", "label": "Debt to capital", "unit": "%", "category": "Leverage",
     "label_i18n": {"zh": "债务资本比", "ar": "الدين إلى رأس المال", "fr": "Dette / Capital"},
     "num": list(_DEBT), "den": _DEBT + [(_EQUITY, 1)],
     "formula": "Total debt / (Total debt + Total equity)"},
    {"key": "debt_ratio", "label": "Debt ratio (liabilities/assets)", "unit": "%", "category": "Leverage",
     "label_i18n": {"zh": "资产负债率", "ar": "نسبة الدين (الالتزامات/الأصول)",
                    "fr": "Ratio d'endettement (passif/actif)"},
     "num": [("bs_non_current_liabilities__total_non_current_liabilities", 1, "opt"),
             (_TCL, 1, "opt")],
     "den": [("bs_total_assets", 1)],
     "formula": "Total liabilities / Total assets"},
    {"key": "debt_to_ebitda", "label": "Total debt / EBITDA", "unit": "x", "category": "Leverage",
     "label_i18n": {"zh": "总债务/EBITDA", "ar": "إجمالي الدين / EBITDA", "fr": "Dette totale / EBITDA"},
     "num": list(_DEBT), "den": list(_EBITDA),
     "formula": "Total debt / EBITDA (EBIT + depreciation & amortisation)"},
    {"key": "net_debt_to_ebitda", "label": "Net debt / EBITDA", "unit": "x", "category": "Leverage",
     "label_i18n": {"zh": "净债务/EBITDA", "ar": "صافي الدين / EBITDA", "fr": "Dette nette / EBITDA"},
     "num": _DEBT + [(k, -1, "opt") for (k, _s, _m) in _CASH], "den": list(_EBITDA),
     "formula": "(Total debt − Cash) / EBITDA"},
    {"key": "equity_multiplier", "label": "Equity multiplier (assets/equity)", "unit": "x",
     "category": "Leverage",
     "label_i18n": {"zh": "权益乘数（资产/权益）", "ar": "مضاعف حقوق الملكية (الأصول/حقوق الملكية)",
                    "fr": "Multiplicateur de capitaux propres (actif/capitaux propres)"},
     "num": [("bs_total_assets", 1)], "den": [(_EQUITY, 1)],
     "formula": "Total assets / Total equity"},
    {"key": "equity_ratio", "label": "Equity ratio", "unit": "%", "category": "Leverage",
     "label_i18n": {"zh": "权益比率", "ar": "نسبة حقوق الملكية", "fr": "Ratio de capitaux propres"},
     "num": [(_EQUITY, 1)], "den": [("bs_total_assets", 1)],
     "formula": "Total equity / Total assets"},

    # ---- Coverage --------------------------------------------------------------------
    {"key": "interest_coverage", "label": "EBIT interest coverage", "unit": "x", "category": "Coverage",
     "label_i18n": {"zh": "利息保障倍数（EBIT）", "ar": "تغطية الفائدة (EBIT)",
                    "fr": "Couverture des intérêts (EBIT)"},
     "num": [("pl_operating_profit_ebit", 1)], "den": [(_INTEREST, 1)],
     "formula": "Operating profit (EBIT) / Interest expense"},
    {"key": "ebitda_interest_coverage", "label": "EBITDA interest coverage", "unit": "x",
     "category": "Coverage",
     "label_i18n": {"zh": "利息保障倍数（EBITDA）", "ar": "تغطية الفائدة (EBITDA)",
                    "fr": "Couverture des intérêts (EBITDA)"},
     "num": list(_EBITDA), "den": [(_INTEREST, 1)],
     "formula": "EBITDA / Interest expense"},
    {"key": "debt_service_coverage", "label": "Debt-service coverage (DSCR)", "unit": "x",
     "category": "Coverage",
     "label_i18n": {"zh": "偿债保障倍数", "ar": "تغطية خدمة الدين", "fr": "Couverture du service de la dette"},
     "num": list(_EBITDA),
     "den": [(_INTEREST, 1),
             ("bs_current_liabilities__current_potion_of_long_term_debt", 1, "opt"),
             ("bs_current_liabilities__current_borrowings", 1, "opt")],
     "formula": "EBITDA / (Interest expense + current portion of long-term debt + current borrowings)"},
    {"key": "cfo_to_total_debt", "label": "Cash flow to total debt", "unit": "%", "category": "Coverage",
     "label_i18n": {"zh": "经营现金流/总债务", "ar": "التدفق النقدي إلى إجمالي الدين",
                    "fr": "Flux de trésorerie / Dette totale"},
     "num": [(_CFO, 1)], "den": list(_DEBT),
     "formula": "Net cash from operating activities / Total debt"},
    {"key": "cfo_interest_coverage", "label": "Cash-flow interest coverage", "unit": "x",
     "category": "Coverage",
     "label_i18n": {"zh": "现金流利息保障倍数", "ar": "تغطية الفائدة من التدفق النقدي",
                    "fr": "Couverture des intérêts par les flux de trésorerie"},
     "num": [(_CFO, 1)], "den": [(_INTEREST, 1)],
     "formula": "Net cash from operating activities / Interest expense"},
    {"key": "fcf_to_total_debt", "label": "Free cash flow to total debt", "unit": "%",
     "category": "Coverage",
     "label_i18n": {"zh": "自由现金流/总债务", "ar": "التدفق النقدي الحر إلى إجمالي الدين",
                    "fr": "Flux de trésorerie disponible / Dette totale"},
     "num": [(_CFO, 1), (_CAPEX, -1, "opt")], "den": list(_DEBT),
     "formula": "(Net cash from operations − Capex) / Total debt"},

    # ---- Efficiency (working-capital cycle) ------------------------------------------
    {"key": "working_capital_to_assets", "label": "Working capital / total assets", "unit": "%",
     "category": "Efficiency",
     "label_i18n": {"zh": "营运资本/总资产", "ar": "رأس المال العامل / إجمالي الأصول",
                    "fr": "Fonds de roulement / Actif total"},
     "num": [("bs_current_assets__total_current_assets", 1), (_TCL, -1)],
     "den": [("bs_total_assets", 1)],
     "formula": "(Total current assets − Total current liabilities) / Total assets"},
    {"key": "dso", "label": "Days sales outstanding (DSO)", "unit": "days", "category": "Efficiency",
     "label_i18n": {"zh": "应收账款周转天数", "ar": "أيام تحصيل الذمم المدينة",
                    "fr": "Délai de recouvrement (jours)"},
     "num": [("bs_current_assets__trade_receivables", 1)],
     "den": [("pl_income__revenue_from_operations", 1)],
     "formula": "Trade receivables / Revenue × 365"},
    {"key": "dio", "label": "Days inventory outstanding (DIO)", "unit": "days", "category": "Efficiency",
     "label_i18n": {"zh": "存货周转天数", "ar": "أيام بقاء المخزون", "fr": "Délai d'écoulement des stocks (jours)"},
     "num": [("bs_current_assets__inventories", 1)],
     "den": [("pl_expenses__cost_of_goods_sold", 1)],
     "formula": "Inventories / Cost of goods sold × 365"},
    {"key": "dpo", "label": "Days payables outstanding (DPO)", "unit": "days", "category": "Efficiency",
     "label_i18n": {"zh": "应付账款周转天数", "ar": "أيام سداد الذمم الدائنة",
                    "fr": "Délai de paiement fournisseurs (jours)"},
     "num": [("bs_current_liabilities__current_trade_payables", 1)],
     "den": [("pl_expenses__cost_of_goods_sold", 1)],
     "formula": "Trade payables / Cost of goods sold × 365"},

    # ---- Profitability ---------------------------------------------------------------
    {"key": "net_margin", "label": "Net profit margin", "unit": "%", "category": "Profitability",
     "label_i18n": {"zh": "净利率", "ar": "هامش صافي الربح", "fr": "Marge nette"},
     "num": [("pl_profit_for_the_year", 1)], "den": [("pl_income__revenue_from_operations", 1)],
     "formula": "Profit for the year / Revenue"},
    {"key": "operating_margin", "label": "Operating margin", "unit": "%", "category": "Profitability",
     "label_i18n": {"zh": "营业利润率", "ar": "هامش التشغيل", "fr": "Marge opérationnelle"},
     "num": [("pl_operating_profit_ebit", 1)], "den": [("pl_income__revenue_from_operations", 1)],
     "formula": "Operating profit (EBIT) / Revenue"},
    {"key": "return_on_equity", "label": "Return on equity", "unit": "%", "category": "Profitability",
     "label_i18n": {"zh": "净资产收益率", "ar": "العائد على حقوق الملكية", "fr": "Rentabilité des capitaux propres"},
     "num": [("pl_profit_for_the_year", 1)], "den": [(_EQUITY, 1)],
     "formula": "Profit for the year / Total equity"},
    {"key": "return_on_assets", "label": "Return on assets", "unit": "%", "category": "Profitability",
     "label_i18n": {"zh": "总资产收益率", "ar": "العائد على الأصول", "fr": "Rentabilité des actifs"},
     "num": [("pl_profit_for_the_year", 1)], "den": [("bs_total_assets", 1)],
     "formula": "Profit for the year / Total assets"},
]


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _value(by_key: dict, key: str, basis: str, period: str) -> float | None:
    row = by_key.get(key)
    if not row:
        return None
    for v in row.get("values") or []:
        if (v.get("basis") or "consolidated") == basis and v.get("period_label") == period:
            return _num(v.get("value"))
    return None


def _side(by_key, terms, basis, period) -> float | None:
    """Sum one side of a ratio. Each term is ``(key, sign)`` — required, missing => whole side
    None — or ``(key, sign, "opt")`` — optional component, missing => treated as 0 (so an
    aggregate like 'total debt' still computes when a company reports only some components).
    The side is None if no term contributed a value at all (nothing to measure)."""
    total = 0.0
    present = False
    for term in terms:
        key, sign = term[0], term[1]
        mode = term[2] if len(term) > 2 else "req"
        val = _value(by_key, key, basis, period)
        if val is None:
            if mode == "opt":
                continue                     # optional component absent → contributes 0
            return None                      # a required input is missing → side unavailable
        total += sign * val
        present = True
    return total if present else None


# unit → (multiplier applied to num/den, suffix formatter)
_UNIT_SCALE = {"x": 1, "%": 100, "days": 365}


def _display(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "%":
        return f"{value}%"
    if unit == "days":
        return f"{value} days"
    return f"{value}×"


# Order categories are shown in (credit-analyst first): liquidity, leverage, coverage, then
# efficiency and profitability.
_CATEGORY_ORDER = ["Liquidity", "Leverage", "Coverage", "Efficiency", "Profitability"]


def compute_ratios(rows: list[dict], *, basis: str = "consolidated", period: str = "current",
                   locale: str = "en") -> list[dict]:
    """Compute the ratio catalog from the extracted values. Ratios missing an input are
    returned as unavailable (never fabricated), so the UI/export can show the full set,
    grouped by category (liquidity / leverage / coverage / efficiency / profitability)."""
    by_key = {r["canonical_key"]: r for r in rows if r.get("canonical_key")}
    computed: dict[str, float | None] = {}
    out: list[dict] = []
    for d in _RATIOS:
        label = (d.get("label_i18n", {}).get(locale) if locale != "en" else None) or d["label"]
        num = _side(by_key, d["num"], basis, period)
        den = _side(by_key, d["den"], basis, period)
        unit = d["unit"]
        available = num is not None and den not in (None, 0)
        value = round((num / den) * _UNIT_SCALE[unit], 2) if available else None
        computed[d["key"]] = value
        out.append({
            "key": d["key"], "label": label, "category": d.get("category", "Profitability"),
            "unit": unit, "formula": d["formula"], "value": value,
            "display": _display(value, unit), "available": available,
        })

    # Cash conversion cycle is a combination of the day-based ratios (DSO + DIO − DPO), so it is
    # derived after the loop from their computed values rather than from raw keys.
    dso, dio, dpo = computed.get("dso"), computed.get("dio"), computed.get("dpo")
    if dso is not None and dio is not None and dpo is not None:
        ccc = round(dso + dio - dpo, 2)
        out.append({
            "key": "cash_conversion_cycle",
            "label": ({"zh": "现金转换周期", "ar": "دورة التحويل النقدي",
                       "fr": "Cycle de conversion de trésorerie"}.get(locale) if locale != "en" else None)
                     or "Cash conversion cycle",
            "category": "Efficiency", "unit": "days",
            "formula": "DSO + DIO − DPO", "value": ccc, "display": _display(ccc, "days"),
            "available": True,
        })

    order = {c: i for i, c in enumerate(_CATEGORY_ORDER)}
    out.sort(key=lambda r: order.get(r["category"], len(order)))
    return out


# --- 2. Disclosures --------------------------------------------------------
_DISCLOSURES = [
    {"key": "auditor_qualification", "label": "Auditor qualification / opinion",
     "label_i18n": {"zh": "审计意见/保留意见", "ar": "تحفّظ المدقق", "fr": "Réserve de l'auditeur"},
     "patterns": [r"qualified opinion", r"adverse opinion", r"disclaimer of opinion",
                  r"emphasis of matter", r"basis for qualified"]},
    {"key": "going_concern", "label": "Going concern",
     "label_i18n": {"zh": "持续经营", "ar": "الاستمرارية", "fr": "Continuité d'exploitation"},
     "patterns": [r"going concern"]},
    {"key": "contingent_liabilities", "label": "Contingent liabilities",
     "label_i18n": {"zh": "或有负债", "ar": "الالتزامات المحتملة", "fr": "Passifs éventuels"},
     "patterns": [r"contingent liabilit", r"contingenc(y|ies)"]},
    {"key": "guarantees", "label": "Guarantees",
     "label_i18n": {"zh": "担保", "ar": "الضمانات", "fr": "Garanties"},
     "patterns": [r"\bguarantee", r"financial guarantee"]},
    {"key": "commitments", "label": "Commitments",
     "label_i18n": {"zh": "承诺事项", "ar": "الالتزامات", "fr": "Engagements"},
     "patterns": [r"capital commitment", r"\bcommitments?\b"]},
    {"key": "related_party", "label": "Related-party transactions",
     "label_i18n": {"zh": "关联方交易", "ar": "معاملات الأطراف ذات العلاقة", "fr": "Parties liées"},
     "patterns": [r"related part(y|ies)"]},
    {"key": "subsequent_events", "label": "Subsequent events",
     "label_i18n": {"zh": "期后事项", "ar": "الأحداث اللاحقة", "fr": "Événements postérieurs"},
     "patterns": [r"subsequent event", r"events after the reporting"]},
    {"key": "litigation", "label": "Litigation / legal proceedings",
     "label_i18n": {"zh": "诉讼", "ar": "التقاضي", "fr": "Litiges"},
     "patterns": [r"litigation", r"legal proceeding", r"lawsuit"]},
]


def _snippet(text: str, match: re.Match, width: int = 90) -> str:
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def scan_disclosures(pages: list[tuple[int, str]], locale: str = "en") -> list[dict]:
    """Scan page texts for the disclosure catalog. Returns one entry per catalog item with
    whether it was found, the page, and a surrounding snippet — a presence check, not a full
    parse (honest about what a generic scan can claim)."""
    out: list[dict] = []
    for d in _DISCLOSURES:
        label = (d["label_i18n"].get(locale) if locale != "en" else None) or d["label"]
        hit = None
        for page_index, text in pages:
            low = text.lower()
            for pat in d["patterns"]:
                m = re.search(pat, low)
                if m:
                    hit = {"page": page_index + 1, "snippet": _snippet(text, m)}
                    break
            if hit:
                break
        out.append({"key": d["key"], "label": label, "present": hit is not None,
                    "page": hit["page"] if hit else None, "snippet": hit["snippet"] if hit else ""})
    return out


def document_text(data: bytes, fmt: str) -> list[tuple[int, str]]:
    """Per-page (or per-sheet) plain text for the disclosure scan."""
    if fmt == "pdf":
        try:
            import fitz
        except ImportError:  # pragma: no cover
            return []
        pdf = fitz.open(stream=data, filetype="pdf")
        return [(i, pdf[i].get_text("text") or "") for i in range(pdf.page_count)]
    if fmt in ("xlsx", "xls"):
        try:
            import io
            import openpyxl
        except ImportError:  # pragma: no cover
            return []
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        pages = []
        for i, name in enumerate(wb.sheetnames):
            cells = [str(c) for row in wb[name].iter_rows(values_only=True) for c in row if c is not None]
            pages.append((i, " ".join(cells)))
        wb.close()
        return pages
    return []


# --- 3. Free-format notes --------------------------------------------------
_NOTE_LINES = [
    ("bs_current_assets__trade_receivables", "Trade receivables"),
    ("bs_current_assets__cash_and_cash_equivalents", "Cash and cash equivalents"),
    ("bs_current_assets__inventories", "Inventories"),
    ("pl_income__revenue_from_operations", "Revenue"),
    ("pl_profit_for_the_year", "Profit for the year"),
]


def _fmt(n: float | None) -> str:
    return "—" if n is None else f"{n:,.0f}"


def build_free_notes(rows: list[dict], *, basis: str = "consolidated", locale: str = "en") -> list[dict]:
    """Plain-language notes generated strictly from the extracted numbers: period movements
    for headline lines, and a one-line read on liquidity/profitability from the ratios."""
    by_key = {r["canonical_key"]: r for r in rows if r.get("canonical_key")}
    notes: list[dict] = []

    for key, label in _NOTE_LINES:
        cur = _value(by_key, key, basis, "current")
        if cur is None:
            continue
        prior = _value(by_key, key, basis, "prior")
        if prior not in (None, 0):
            delta = (cur - prior) / abs(prior) * 100
            direction = "increased" if delta >= 0 else "decreased"
            notes.append({
                "title": label,
                "text": f"{label} {direction} {abs(delta):.1f}% to {_fmt(cur)} "
                        f"(prior period {_fmt(prior)}).",
            })
        else:
            notes.append({"title": label, "text": f"{label} was {_fmt(cur)} for the current period."})

    ratios = {r["key"]: r for r in compute_ratios(rows, basis=basis)}
    cr = ratios.get("current_ratio")
    if cr and cr["available"]:
        stance = "comfortable" if cr["value"] >= 1.5 else "adequate" if cr["value"] >= 1 else "tight"
        notes.append({"title": "Liquidity",
                      "text": f"Current ratio of {cr['display']} indicates {stance} short-term liquidity."})
    nm = ratios.get("net_margin")
    if nm and nm["available"]:
        notes.append({"title": "Profitability",
                      "text": f"Net profit margin was {nm['display']} of revenue."})

    if not notes:
        notes.append({"title": "Summary",
                      "text": "Not enough headline values were extracted to generate movement notes."})
    return notes

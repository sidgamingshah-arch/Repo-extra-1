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
_RATIOS = [
    {"key": "current_ratio", "label": "Current ratio", "unit": "x",
     "label_i18n": {"zh": "流动比率", "ar": "نسبة التداول", "fr": "Ratio de liquidité générale"},
     "num": [("bs_current_assets__total_current_assets", 1)],
     "den": [("bs_current_liabilities__total_current_liabilities", 1)],
     "formula": "Total current assets / Total current liabilities"},
    {"key": "quick_ratio", "label": "Quick ratio", "unit": "x",
     "label_i18n": {"zh": "速动比率", "ar": "نسبة السيولة السريعة", "fr": "Ratio de liquidité réduite"},
     "num": [("bs_current_assets__total_current_assets", 1), ("bs_current_assets__inventories", -1)],
     "den": [("bs_current_liabilities__total_current_liabilities", 1)],
     "formula": "(Total current assets − Inventories) / Total current liabilities"},
    {"key": "debt_to_equity", "label": "Debt to equity", "unit": "x",
     "label_i18n": {"zh": "负债权益比", "ar": "نسبة الدين إلى حقوق الملكية", "fr": "Dette / Capitaux propres"},
     "num": [("bs_non_current_liabilities__total_non_current_liabilities", 1),
             ("bs_current_liabilities__total_current_liabilities", 1)],
     "den": [("bs_equity__total_equity", 1)],
     "formula": "(Non-current + current liabilities) / Total equity"},
    {"key": "equity_ratio", "label": "Equity ratio", "unit": "%",
     "label_i18n": {"zh": "权益比率", "ar": "نسبة حقوق الملكية", "fr": "Ratio de capitaux propres"},
     "num": [("bs_equity__total_equity", 1)], "den": [("bs_total_assets", 1)],
     "formula": "Total equity / Total assets"},
    {"key": "net_margin", "label": "Net profit margin", "unit": "%",
     "label_i18n": {"zh": "净利率", "ar": "هامش صافي الربح", "fr": "Marge nette"},
     "num": [("pl_profit_for_the_year", 1)], "den": [("pl_income__revenue_from_operations", 1)],
     "formula": "Profit for the year / Revenue"},
    {"key": "operating_margin", "label": "Operating margin", "unit": "%",
     "label_i18n": {"zh": "营业利润率", "ar": "هامش التشغيل", "fr": "Marge opérationnelle"},
     "num": [("pl_operating_profit_ebit", 1)], "den": [("pl_income__revenue_from_operations", 1)],
     "formula": "Operating profit (EBIT) / Revenue"},
    {"key": "return_on_equity", "label": "Return on equity", "unit": "%",
     "label_i18n": {"zh": "净资产收益率", "ar": "العائد على حقوق الملكية", "fr": "Rentabilité des capitaux propres"},
     "num": [("pl_profit_for_the_year", 1)], "den": [("bs_equity__total_equity", 1)],
     "formula": "Profit for the year / Total equity"},
    {"key": "return_on_assets", "label": "Return on assets", "unit": "%",
     "label_i18n": {"zh": "总资产收益率", "ar": "العائد على الأصول", "fr": "Rentabilité des actifs"},
     "num": [("pl_profit_for_the_year", 1)], "den": [("bs_total_assets", 1)],
     "formula": "Profit for the year / Total assets"},
    {"key": "interest_coverage", "label": "Interest coverage", "unit": "x",
     "label_i18n": {"zh": "利息保障倍数", "ar": "تغطية الفائدة", "fr": "Couverture des intérêts"},
     "num": [("pl_operating_profit_ebit", 1)],
     "den": [("pl_non_operating_expenses__interest_expense", 1)],
     "formula": "Operating profit (EBIT) / Interest expense"},
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


def _sum(by_key, terms, basis, period) -> float | None:
    total = 0.0
    for key, sign in terms:
        val = _value(by_key, key, basis, period)
        if val is None:
            return None                      # every input must be present
        total += sign * val
    return total


def compute_ratios(rows: list[dict], *, basis: str = "consolidated", period: str = "current",
                   locale: str = "en") -> list[dict]:
    """Compute the ratio catalog from the extracted values. Ratios missing an input are
    returned as unavailable (with the reason), so the UI/export can show the full set."""
    by_key = {r["canonical_key"]: r for r in rows if r.get("canonical_key")}
    out: list[dict] = []
    for d in _RATIOS:
        label = (d["label_i18n"].get(locale) if locale != "en" else None) or d["label"]
        num = _sum(by_key, d["num"], basis, period)
        den = _sum(by_key, d["den"], basis, period)
        available = num is not None and den not in (None, 0)
        value = round((num / den) * (100 if d["unit"] == "%" else 1), 2) if available else None
        display = (f"{value}%" if d["unit"] == "%" else f"{value}×") if available else "—"
        out.append({
            "key": d["key"], "label": label, "unit": d["unit"], "formula": d["formula"],
            "value": value, "display": display, "available": available,
        })
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

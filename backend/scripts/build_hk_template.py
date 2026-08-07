#!/usr/bin/env python3
"""Generate the HK/China (HKFRS/IFRS) financial template + a matching ontology.

Emits two JSON files under app/sample/templates/:
  * hkfrs_hk_china_template.json  — the output template (sections → lines → subtotals,
    statement-level totals, rollups, and the balance-sheet identity). English + Chinese
    (zh) labels for multilingual parity.
  * hkfrs_hk_china_ontology.json  — a companion ontology whose per-concept *descriptions*
    (section + statement context) drive the tool's description-based LLM mapping, which
    is how the many repeated "Others" / "Total …" captions get disambiguated by meaning.

Both validate against app/schemas + loader and are cross-checked (ontology keys ⊆
template keys). Run:  python scripts/build_hk_template.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (title, subheading, name, isTotal) — the caller's rows, plus an expanded cash flow.
ROWS: list[tuple[str, str, str, bool]] = [
    # ---------------- Balance Sheet ----------------
    ("Balance Sheet", "", "Non-current assets", False),
    ("Balance Sheet", "Non-current assets", "Property, Plant and Equipment", False),
    ("Balance Sheet", "Non-current assets", "Land of use rights", False),
    ("Balance Sheet", "Non-current assets", "Right-of-use assets", False),
    ("Balance Sheet", "Non-current assets", "Construction in progress", False),
    ("Balance Sheet", "Non-current assets", "Investment Properties", False),
    ("Balance Sheet", "Non-current assets", "Goodwill", False),
    ("Balance Sheet", "Non-current assets", "Other Intangible assets", False),
    ("Balance Sheet", "Non-current assets", "Intangible assets under development", False),
    ("Balance Sheet", "Non-current assets", "Investments in subsidiaries", False),
    ("Balance Sheet", "Non-current assets", "Interests in associates", False),
    ("Balance Sheet", "Non-current assets", "Equity investments designated at fair value through other comprehensive income", False),
    ("Balance Sheet", "Non-current assets", "Financial assets at fair value through profit or loss", False),
    ("Balance Sheet", "Non-current assets", "Other non-current financial assets", False),
    ("Balance Sheet", "Non-current assets", "Deferred Income Tax Assets", False),
    ("Balance Sheet", "Non-current assets", "Term Deposits", False),
    ("Balance Sheet", "Non-current assets", "Others", False),
    ("Balance Sheet", "Non-current assets", "Total non-current assets", True),
    ("Balance Sheet", "", "Current assets", False),
    ("Balance Sheet", "Current assets", "Cash and cash equivalents", False),
    ("Balance Sheet", "Current assets", "Bank balances other than cash and cash equivalents", False),
    ("Balance Sheet", "Current assets", "Inventories", False),
    ("Balance Sheet", "Current assets", "Trade receivables", False),
    ("Balance Sheet", "Current assets", "Prepayments, other receivables and other assets", False),
    ("Balance Sheet", "Current assets", "Financial assets at fair value through other comprehensive income", False),
    ("Balance Sheet", "Current assets", "Other Financial Assets", False),
    ("Balance Sheet", "Current assets", "Others", False),
    ("Balance Sheet", "Current assets", "Total current assets", True),
    ("Balance Sheet", "", "Total Assets", True),
    ("Balance Sheet", "", "Equity", False),
    ("Balance Sheet", "Equity", "Share capital", False),
    ("Balance Sheet", "Equity", "Other equity instruments", False),
    ("Balance Sheet", "Equity", "Capital reserve", False),
    ("Balance Sheet", "Equity", "Share Premium", False),
    ("Balance Sheet", "Equity", "Treasury Shares", False),
    ("Balance Sheet", "Equity", "Shares held for share award schemes", False),
    ("Balance Sheet", "Equity", "Retained earnings", False),
    ("Balance Sheet", "Equity", "General Reserve", False),
    ("Balance Sheet", "Equity", "Other comprehensive income reserve", False),
    ("Balance Sheet", "Equity", "Non-controlling interests", False),
    ("Balance Sheet", "Equity", "Others", False),
    ("Balance Sheet", "Equity", "Total equity", True),
    ("Balance Sheet", "", "Non-current liabilities", False),
    ("Balance Sheet", "Non-current liabilities", "Non-current borrowings", False),
    ("Balance Sheet", "Non-current liabilities", "Non-current Bonds payable", False),
    ("Balance Sheet", "Non-current liabilities", "Non-current Notes Payable", False),
    ("Balance Sheet", "Non-current liabilities", "Non-current Lease liabilities", False),
    ("Balance Sheet", "Non-current liabilities", "Long-term provisions", False),
    ("Balance Sheet", "Non-current liabilities", "Long-term payables", False),
    ("Balance Sheet", "Non-current liabilities", "Non-current Deferred tax liabilities (net)", False),
    ("Balance Sheet", "Non-current liabilities", "Non-current Deferred income", False),
    ("Balance Sheet", "Non-current liabilities", "Others", False),
    ("Balance Sheet", "Non-current liabilities", "Total non-current liabilities", True),
    ("Balance Sheet", "", "Current liabilities", False),
    ("Balance Sheet", "Current liabilities", "Current borrowings", False),
    ("Balance Sheet", "Current liabilities", "Current potion of long term debt", False),
    ("Balance Sheet", "Current liabilities", "Other current financial liabilities", False),
    ("Balance Sheet", "Current liabilities", "Current Trade payables", False),
    ("Balance Sheet", "Current liabilities", "Cuurent Notes Payable", False),
    ("Balance Sheet", "Current liabilities", "Current income tax liabilities", False),
    ("Balance Sheet", "Current liabilities", "Current Lease Liabilities", False),
    ("Balance Sheet", "Current liabilities", "Current Deferred Revenue", False),
    ("Balance Sheet", "Current liabilities", "Others", False),
    ("Balance Sheet", "Current liabilities", "Total current liabilities", True),
    ("Balance Sheet", "", "Total Equity and Liabilities", True),
    # ---------------- Profit & Loss ----------------
    ("Profit & Loss", "", "Income", False),
    ("Profit & Loss", "Income", "Revenue from operations", False),
    ("Profit & Loss", "Income", "Other income", False),
    ("Profit & Loss", "Income", "Total income", True),
    ("Profit & Loss", "", "Expenses", False),
    ("Profit & Loss", "Expenses", "Cost of Goods Sold", False),
    ("Profit & Loss", "Expenses", "Selling and Marketing Expenses", False),
    ("Profit & Loss", "Expenses", "General and Administrative expenses", False),
    ("Profit & Loss", "Expenses", "Research and development expenses", False),
    ("Profit & Loss", "Expenses", "Employee benefits expense", False),
    ("Profit & Loss", "Expenses", "Purchases of Stock-in-trade", False),
    ("Profit & Loss", "Expenses", "Other Operating costs", False),
    ("Profit & Loss", "Expenses", "Depreciation and Amortisation Expense", False),
    ("Profit & Loss", "Expenses", "Total operating cost", True),
    ("Profit & Loss", "", "Operating Profit / EBIT", True),
    ("Profit & Loss", "", "Non-operating expenses", False),
    ("Profit & Loss", "Non-operating expenses", "Interest Expense", False),
    ("Profit & Loss", "Non-operating expenses", "Interest Income", False),
    ("Profit & Loss", "Non-operating expenses", "Investment income", False),
    ("Profit & Loss", "Non-operating expenses", "Others", False),
    ("Profit & Loss", "Non-operating expenses", "Total non-operating expense", True),
    ("Profit & Loss", "", "Total expenses", True),
    ("Profit & Loss", "", "Profit before exceptional items and tax", True),
    ("Profit & Loss", "", "Exceptional items", False),
    ("Profit & Loss", "Exceptional items", "share of profit of associates and JVs", False),
    ("Profit & Loss", "Exceptional items", "Gain on derecognition of financial assets at amortised cost", False),
    ("Profit & Loss", "Exceptional items", "Fair value change gains", False),
    ("Profit & Loss", "Exceptional items", "Credit impairment losses", False),
    ("Profit & Loss", "Exceptional items", "Asset impairment losses", False),
    ("Profit & Loss", "Exceptional items", "Gains on asset disposal", False),
    ("Profit & Loss", "Exceptional items", "Total Exceptional items", True),
    ("Profit & Loss", "", "Profit before tax", True),
    ("Profit & Loss", "", "Tax expense", False),
    ("Profit & Loss", "Tax expense", "Current tax", False),
    ("Profit & Loss", "Tax expense", "Deferred tax", False),
    ("Profit & Loss", "Tax expense", "Others", False),
    ("Profit & Loss", "Tax expense", "Total tax expense", True),
    ("Profit & Loss", "", "Profit for the year", True),
    # ---------------- Cash Flow (expanded) ----------------
    ("Cash Flow", "", "Cash flow from operating activities", False),
    ("Cash Flow", "Cash flow from operating activities", "Profit before tax", False),
    ("Cash Flow", "Cash flow from operating activities", "Income tax expense", False),
    ("Cash Flow", "Cash flow from operating activities", "Depreciation and amortisation", False),
    ("Cash Flow", "Cash flow from operating activities", "Finance costs", False),
    ("Cash Flow", "Cash flow from operating activities", "Interest income", False),
    ("Cash Flow", "Cash flow from operating activities", "Share of results of associates and joint ventures", False),
    ("Cash Flow", "Cash flow from operating activities", "Fair value changes on financial instruments", False),
    ("Cash Flow", "Cash flow from operating activities", "Impairment losses on financial and contract assets", False),
    ("Cash Flow", "Cash flow from operating activities", "Loss/(gain) on disposal of property, plant and equipment", False),
    ("Cash Flow", "Cash flow from operating activities", "(Increase)/decrease in trade receivables", False),
    ("Cash Flow", "Cash flow from operating activities", "(Increase)/decrease in inventories", False),
    ("Cash Flow", "Cash flow from operating activities", "(Increase)/decrease in prepayments and other receivables", False),
    ("Cash Flow", "Cash flow from operating activities", "Increase/(decrease) in trade payables", False),
    ("Cash Flow", "Cash flow from operating activities", "Increase/(decrease) in contract liabilities", False),
    ("Cash Flow", "Cash flow from operating activities", "Increase/(decrease) in other payables and accruals", False),
    ("Cash Flow", "Cash flow from operating activities", "Cash generated from operations", False),
    ("Cash Flow", "Cash flow from operating activities", "Interest received", False),
    ("Cash Flow", "Cash flow from operating activities", "Income tax paid", False),
    ("Cash Flow", "Cash flow from operating activities", "Others", False),
    ("Cash Flow", "Cash flow from operating activities", "Net cash from operating activities", True),
    ("Cash Flow", "", "Cash flow from investing activities", False),
    ("Cash Flow", "Cash flow from investing activities", "Purchase of property, plant and equipment", False),
    ("Cash Flow", "Cash flow from investing activities", "Purchase of intangible assets", False),
    ("Cash Flow", "Cash flow from investing activities", "Additions to investment properties", False),
    ("Cash Flow", "Cash flow from investing activities", "Proceeds from disposal of property, plant and equipment", False),
    ("Cash Flow", "Cash flow from investing activities", "Purchase of investments", False),
    ("Cash Flow", "Cash flow from investing activities", "Proceeds from sale of investments", False),
    ("Cash Flow", "Cash flow from investing activities", "Acquisition of subsidiaries, net of cash acquired", False),
    ("Cash Flow", "Cash flow from investing activities", "Disposal of subsidiaries, net of cash disposed", False),
    ("Cash Flow", "Cash flow from investing activities", "Dividends received from associates and investments", False),
    ("Cash Flow", "Cash flow from investing activities", "Interest received", False),
    ("Cash Flow", "Cash flow from investing activities", "(Placement)/withdrawal of time deposits", False),
    ("Cash Flow", "Cash flow from investing activities", "Others", False),
    ("Cash Flow", "Cash flow from investing activities", "Net cash used in investing activities", True),
    ("Cash Flow", "", "Cash flow from financing activities", False),
    ("Cash Flow", "Cash flow from financing activities", "Proceeds from borrowings", False),
    ("Cash Flow", "Cash flow from financing activities", "Repayment of borrowings", False),
    ("Cash Flow", "Cash flow from financing activities", "Proceeds from issue of shares", False),
    ("Cash Flow", "Cash flow from financing activities", "Repurchase of shares", False),
    ("Cash Flow", "Cash flow from financing activities", "Proceeds from issue of bonds and notes", False),
    ("Cash Flow", "Cash flow from financing activities", "Redemption of bonds and notes", False),
    ("Cash Flow", "Cash flow from financing activities", "Principal elements of lease payments", False),
    ("Cash Flow", "Cash flow from financing activities", "Dividends paid", False),
    ("Cash Flow", "Cash flow from financing activities", "Dividends paid to non-controlling interests", False),
    ("Cash Flow", "Cash flow from financing activities", "Capital contributions from non-controlling interests", False),
    ("Cash Flow", "Cash flow from financing activities", "Interest paid", False),
    ("Cash Flow", "Cash flow from financing activities", "Others", False),
    ("Cash Flow", "Cash flow from financing activities", "Net cash from financing activities", True),
    ("Cash Flow", "", "Net increase/(decrease) in cash and cash equivalents", True),
    ("Cash Flow", "", "Effect of foreign exchange rate changes", False),
    ("Cash Flow", "", "Opening cash and cash equivalents", True),
    ("Cash Flow", "", "Closing cash and cash equivalents", True),
]

STMT_TYPE = {"Balance Sheet": "balance_sheet", "Profit & Loss": "profit_and_loss", "Cash Flow": "cash_flow"}
STMT_CODE = {"Balance Sheet": "bs", "Profit & Loss": "pl", "Cash Flow": "cf"}
STMT_HUMAN = {"Balance Sheet": "balance sheet", "Profit & Loss": "statement of profit or loss", "Cash Flow": "statement of cash flows"}

# Chinese (Simplified) labels for the standard HKFRS/IFRS concepts (best-effort; missing
# entries fall back to English). Keyed by the English name exactly as above.
ZH = {
    "Non-current assets": "非流动资产", "Property, Plant and Equipment": "物业、厂房及设备",
    "Land of use rights": "土地使用权", "Right-of-use assets": "使用权资产",
    "Construction in progress": "在建工程", "Investment Properties": "投资物业",
    "Goodwill": "商誉", "Other Intangible assets": "其他无形资产",
    "Intangible assets under development": "在建无形资产", "Investments in subsidiaries": "于子公司的投资",
    "Interests in associates": "于联营公司的权益",
    "Equity investments designated at fair value through other comprehensive income": "指定以公允价值计量且其变动计入其他综合收益的权益投资",
    "Financial assets at fair value through profit or loss": "以公允价值计量且其变动计入损益的金融资产",
    "Other non-current financial assets": "其他非流动金融资产", "Deferred Income Tax Assets": "递延所得税资产",
    "Term Deposits": "定期存款", "Others": "其他", "Total non-current assets": "非流动资产总额",
    "Current assets": "流动资产", "Cash and cash equivalents": "现金及现金等价物",
    "Bank balances other than cash and cash equivalents": "除现金及现金等价物以外的银行结余",
    "Inventories": "存货", "Trade receivables": "应收账款",
    "Prepayments, other receivables and other assets": "预付款项、其他应收款及其他资产",
    "Financial assets at fair value through other comprehensive income": "以公允价值计量且其变动计入其他综合收益的金融资产",
    "Other Financial Assets": "其他金融资产", "Total current assets": "流动资产总额", "Total Assets": "资产总额",
    "Equity": "权益", "Share capital": "股本", "Other equity instruments": "其他权益工具",
    "Capital reserve": "资本公积", "Share Premium": "股份溢价", "Treasury Shares": "库存股",
    "Shares held for share award schemes": "为股份奖励计划持有的股份", "Retained earnings": "留存收益",
    "General Reserve": "一般储备", "Other comprehensive income reserve": "其他综合收益储备",
    "Non-controlling interests": "非控制性权益", "Total equity": "权益总额",
    "Non-current liabilities": "非流动负债", "Non-current borrowings": "非流动借款",
    "Non-current Bonds payable": "非流动应付债券", "Non-current Notes Payable": "非流动应付票据",
    "Non-current Lease liabilities": "非流动租赁负债", "Long-term provisions": "长期拨备",
    "Long-term payables": "长期应付款", "Non-current Deferred tax liabilities (net)": "非流动递延税项负债（净额）",
    "Non-current Deferred income": "非流动递延收益", "Total non-current liabilities": "非流动负债总额",
    "Current liabilities": "流动负债", "Current borrowings": "流动借款",
    "Current potion of long term debt": "长期负债的流动部分", "Other current financial liabilities": "其他流动金融负债",
    "Current Trade payables": "流动应付账款", "Cuurent Notes Payable": "流动应付票据",
    "Current income tax liabilities": "流动所得税负债", "Current Lease Liabilities": "流动租赁负债",
    "Current Deferred Revenue": "流动递延收入", "Total current liabilities": "流动负债总额",
    "Total Equity and Liabilities": "权益及负债总额",
    "Income": "收入", "Revenue from operations": "营业收入", "Other income": "其他收入", "Total income": "收入总额",
    "Expenses": "费用", "Cost of Goods Sold": "销售成本", "Selling and Marketing Expenses": "销售及市场推广费用",
    "General and Administrative expenses": "一般及行政费用", "Research and development expenses": "研发费用",
    "Employee benefits expense": "员工福利开支", "Purchases of Stock-in-trade": "存货采购",
    "Other Operating costs": "其他营业成本", "Depreciation and Amortisation Expense": "折旧及摊销费用",
    "Total operating cost": "营业成本总额", "Operating Profit / EBIT": "营业利润/息税前利润",
    "Non-operating expenses": "营业外收支", "Interest Expense": "利息支出", "Interest Income": "利息收入",
    "Investment income": "投资收益", "Total non-operating expense": "营业外收支总额", "Total expenses": "费用总额",
    "Profit before exceptional items and tax": "非经常性项目及税前利润", "Exceptional items": "非经常性项目",
    "share of profit of associates and JVs": "应占联营及合营企业利润",
    "Gain on derecognition of financial assets at amortised cost": "终止确认以摊余成本计量金融资产的收益",
    "Fair value change gains": "公允价值变动收益", "Credit impairment losses": "信用减值损失",
    "Asset impairment losses": "资产减值损失", "Gains on asset disposal": "资产处置收益",
    "Total Exceptional items": "非经常性项目总额", "Profit before tax": "税前利润", "Tax expense": "所得税费用",
    "Current tax": "当期所得税", "Deferred tax": "递延所得税", "Total tax expense": "所得税费用总额",
    "Profit for the year": "年度利润",
    "Cash flow from operating activities": "经营活动现金流量", "Income tax expense": "所得税费用",
    "Depreciation and amortisation": "折旧及摊销", "Finance costs": "财务费用",
    "(Increase)/decrease in trade receivables": "应收账款的（增加）/减少",
    "(Increase)/decrease in inventories": "存货的（增加）/减少",
    "Increase/(decrease) in trade payables": "应付账款的增加/（减少）",
    "Net cash from operating activities": "经营活动产生的现金流量净额",
    "Cash flow from investing activities": "投资活动现金流量",
    "Purchase of property, plant and equipment": "购建物业、厂房及设备",
    "Proceeds from sale of investments": "出售投资所得款项", "Purchase of investments": "购买投资",
    "Net cash used in investing activities": "投资活动所用现金流量净额",
    "Cash flow from financing activities": "筹资活动现金流量", "Proceeds from borrowings": "借款所得款项",
    "Repayment of borrowings": "偿还借款", "Dividends paid": "已付股利", "Interest paid": "已付利息",
    "Net cash from financing activities": "筹资活动产生的现金流量净额",
    "Net increase/(decrease) in cash and cash equivalents": "现金及现金等价物增加/（减少）净额",
    "Opening cash and cash equivalents": "期初现金及现金等价物",
    "Closing cash and cash equivalents": "期末现金及现金等价物",
    "Effect of foreign exchange rate changes": "汇率变动的影响",
    "Interest received": "已收利息", "Income tax paid": "已付所得税",
    "Cash generated from operations": "经营活动产生的现金",
}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return re.sub(r"_+", "_", s)


def node(node_id, name, role, section_zh=None, rollup=None):
    n = {"node_id": node_id, "canonical_key": node_id, "label": name, "role": role}
    if name in ZH:
        n["label_i18n"] = {"en": name, "zh": ZH[name]}
    if rollup:
        n["rollup"] = {"op": "sum", "children": rollup}
    return n


def build():
    statements: dict[str, dict] = {}
    order: list[str] = []
    # Track, per statement, section node + its line children, and subtotal/total ids.
    for title, sub, name, is_total in ROWS:
        st = statements.setdefault(title, {"sections": [], "cur": None, "subtotals": {}, "totals": []})
        if title not in order:
            order.append(title)
        code = STMT_CODE[title]
        if sub == "" and not is_total:
            # Section header — open a new section container.
            sec_idx = len([s for s in st["sections"]]) + 1
            sid = f"{code}_s{sec_idx}_{slug(name)}"
            sec = node(sid, name, "header")
            sec["children"] = []
            sec["_name"] = name
            st["sections"].append(sec)
            st["cur"] = sec
        elif sub == "" and is_total:
            # Statement-level total.
            tid = f"{code}_{slug(name)}"
            st["totals"].append(node(tid, name, "total"))
            st["cur"] = None
        else:
            # A line (or the section subtotal) under the current/last matching section.
            sec = next((s for s in st["sections"] if s["_name"] == sub), None)
            if sec is None:  # a subheading with no explicit header row → synthesise one
                sec_idx = len(st["sections"]) + 1
                sec = node(f"{code}_s{sec_idx}_{slug(sub)}", sub, "header")
                sec["children"] = []
                sec["_name"] = sub
                st["sections"].append(sec)
            nid = f"{code}_{slug(sub)}__{slug(name)}"
            if is_total:
                line_ids = [c["node_id"] for c in sec["children"] if c["role"] == "line"]
                sec["children"].append(node(nid, name, "subtotal", rollup=line_ids))
                st["subtotals"][sub] = nid
            else:
                sec["children"].append(node(nid, name, "line"))

    # Wire the obvious statement-level rollups + the balance-sheet identity.
    defs = []
    for title in order:
        st = statements[title]
        subs = st["subtotals"]
        totals = {t["label"]: t for t in st["totals"]}

        def wire(total_label, section_labels):
            t = totals.get(total_label)
            if not t:
                return
            kids = [subs[s] for s in section_labels if s in subs]
            if kids:
                t["rollup"] = {"op": "sum", "children": kids}

        if title == "Balance Sheet":
            wire("Total Assets", ["Non-current assets", "Current assets"])
            wire("Total Equity and Liabilities", ["Equity", "Non-current liabilities", "Current liabilities"])
        if title == "Cash Flow":
            net = totals.get("Net increase/(decrease) in cash and cash equivalents")
            act = [subs.get(s) for s in ("Cash flow from operating activities",
                                         "Cash flow from investing activities",
                                         "Cash flow from financing activities")]
            act = [a for a in act if a]
            if net and act:
                net["rollup"] = {"op": "sum", "children": act}

        # Assemble sections (strip the private _name marker) + statement totals as
        # top-level nodes, preserving original order via a merged list.
        sections = []
        for s in st["sections"]:
            s.pop("_name", None)
            for c in s["children"]:
                c.pop("_name", None)
            sections.append(s)
        sections.extend(st["totals"])

        stmt = {"type": STMT_TYPE[title], "sections": sections}
        if title == "Balance Sheet" and "bs_total_assets" and totals.get("Total Assets") and totals.get("Total Equity and Liabilities"):
            stmt["identities"] = [{
                "id": "bs_balances",
                "lhs": totals["Total Assets"]["node_id"],
                "rhs": {"op": "sum", "children": [totals["Total Equity and Liabilities"]["node_id"]]},
            }]
        defs.append(stmt)

    template = {
        "schema_version": 1,
        "template_key": "hkfrs_hk_china_v1",
        "name": "HKFRS / IFRS Standard Spread — Hong Kong / China (v1)",
        "statements": defs,
    }
    return template


def build_ontology(template: dict) -> dict:
    """Companion ontology: a concept per template key, with a context-rich description so
    description-based mapping disambiguates repeated captions (e.g. the many 'Others')."""
    mappings = []
    for st in template["statements"]:
        human = next(h for t, h in STMT_HUMAN.items() if STMT_TYPE[t] == st["type"])

        def walk(nodes, section_label=None):
            for n in nodes:
                role = n.get("role")
                if role in ("line", "subtotal", "total"):
                    label = n["label"]
                    where = f"under '{section_label}' in the {human}" if section_label else f"a top-level line of the {human}"
                    desc = f"{label}: {where}."
                    m = {
                        "canonical_key": n["canonical_key"], "label": label, "description": desc,
                        "aliases": [label],
                    }
                    zh = n.get("label_i18n", {}).get("zh")
                    if zh:
                        m["aliases_i18n"] = {"en": [label], "zh": [zh]}
                    mappings.append(m)
                if n.get("children"):
                    walk(n["children"], n["label"] if role == "header" else section_label)

        walk(st["sections"])

    return {
        "schema_version": 1,
        "ontology_key": "hkfrs_hk_china_v1",
        "target_template_key": template["template_key"],
        "locale": "en",
        "supported_locales": ["en", "zh"],
        "number_format_by_locale": {"en": {}, "zh": {}},
        "mappings": mappings,
    }


def main() -> int:
    template = build()
    ontology = build_ontology(template)

    # Validate against the real schemas + cross-check before writing.
    from app.schemas.loader import (
        load_ontology, load_template, validate_ontology_against_template, validate_template,
    )

    tpl = load_template(template)
    terrs = validate_template(tpl)
    ont = load_ontology(ontology)
    oerrs = validate_ontology_against_template(ont, tpl)
    assert not terrs, terrs
    assert not oerrs, oerrs

    out = Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"
    out.mkdir(parents=True, exist_ok=True)
    (out / "hkfrs_hk_china_template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2))
    (out / "hkfrs_hk_china_ontology.json").write_text(json.dumps(ontology, ensure_ascii=False, indent=2))
    print(f"template keys: {len(tpl.all_canonical_keys())}  ontology mappings: {len(ont.mappings)}")
    print(f"wrote {out}/hkfrs_hk_china_template.json and _ontology.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

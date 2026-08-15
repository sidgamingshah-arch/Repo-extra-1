"""Rewrite the shipped template's balance sheet to the revised specification.

Applied once and kept, because the spec it encodes is reviewable here in a way 85 hand-edited JSON
nodes are not, and the profit-and-loss and cash-flow revisions will follow the same shape. Every
edit is add-or-replace, so running it twice leaves the same files.

What this changes, and why each matters:

* HK LADDER ORDER. Current liabilities now sit before non-current ones, with the ladder totals
  interleaved (net current assets → total assets less current liabilities → net assets), which is how
  an HKEX filing presents a balance sheet. The previous order put both liability sections after equity
  and left the ladder totals stranded at the bottom.

* SECTION IDS FOLLOW THE NEW ORDER, and the rulebook's section layer is renamed with them. The ids
  are positional (``bs_s3_…`` is the third section), so leaving current liabilities called
  ``bs_s5_current_liabilities`` in third place would make the name lie about the position.

  To be accurate about what this does and does not matter for: the matching gate does NOT compare
  these ids to the template's. ``mapping.section_token_of_scope`` reads the section name off the END
  of a scope id (``bs_s3_current_liabilities`` and ``bs_s5_current_liabilities`` both resolve to the
  token ``current_liabilities``), so the number is decorative to the gate and the rename is safe
  rather than required. What it IS required to be is internally consistent: the rulebook's
  ``section_defaults`` is keyed by section id, each of its concepts names one through
  ``inherits``, two residuals name one again under ``residual_policy.section_scope``, and
  ``services/ontology_skeleton.py`` writes ``inherits`` from the template's node_ids.
  ``rename_sections`` moves every one of them together, through a temporary name because equity and
  current liabilities SWAP ids.

* TWO CANONICAL-KEY TYPOS FIXED: ``cuurent_notes_payable`` and ``current_potion_of_long_term_debt``.
  These are the identifiers the ontology maps captions onto, and they were referenced from more than
  the ``canonical_key`` field they name — five ``confusable_with`` entries, the notes-payable family
  in ``services/mapping.py``, and the total-debt term list in ``services/derived.py``. See
  ``revise_keys`` for what the rename covers and what it costs a stored run.

* THE BALANCE CHECK BECOMES A REAL TEST. ``bs_net_assets`` was ``SUM(bs_equity__total_equity)`` — net
  assets defined as equity, so the one relation that proves a balance sheet balances was an identity
  with itself and could never fail. It is now the asset-side ladder
  (total assets less current liabilities − total non-current liabilities), which is what makes the
  rulebook's existing ``bs_net_assets_equals_equity`` a relation that can break. A tautology that
  reads as a passing check is worse than no check: it consumes a slot in the coverage report and
  reports success.

* EQUITY IS RESTRUCTURED. Reserves now absorbs share premium, treasury shares and shares held for
  award schemes alongside the four reserve captions, and ``equity_attributable_to_owners`` is a new
  node between reserves and total equity. Total equity is therefore reached in two steps
  (owners' + NCI) rather than one flat sum, which is what lets a break in the attribution be seen.

* ONE NEW CONCEPT, ``bs_current_assets__contract_assets``, seeded by ``seed_contract_assets``: a
  template line no rulebook recognises is a line that can never be filled.

* ONE NEW CHECK, not the three the spec lists, because the revised structure already enforces the
  other two. ``bs_check_equity_attribution`` (owners' + NCI = total equity) and
  ``bs_check_reserves_composition`` (the eight parts sum to reserves) are letter-for-letter the
  arithmetic of the new ``bs_equity__total_equity`` and ``bs_equity__reserves`` ROLLUPS — the
  restructure is what made them checkable, and declaring them again as rulebook identities would put
  each fact in the coverage denominator twice and raise two review cards for one break. So only
  ``bs_check_derived_consistency`` is added: it reaches net assets through total assets while the
  ladder reaches it through net current assets, which no rollup asserts.

  One consequence to be explicit about: the spec asks for reserves composition at ``severity:warn``
  and a rollup is always blocking (``structural_checks.Relation.severity`` defaults to it, and there
  is no per-rollup severity field). It behaves as the spec's ``skip_if_either_side_absent`` intends —
  a filing printing only a reserves total leaves the components unextracted and the relation is
  SKIPPED, not failed — but where both are printed and disagree, the card is blocking rather than a
  warning. Making that tunable means a severity field on ``Rollup``, which is a schema change beyond
  this revision.

* ONE CHECK DELETED: the rulebook's ``bs_balance`` was the template's ``bs_balances`` in different
  words — the same footing equation declared in both the template and the rulebook, counted twice
  in coverage. See ``DROP_IDENTITIES``.

WHAT THE SPEC ASKED FOR AND THIS DOES NOT ENCODE — one item, stated rather than quietly dropped:
``COALESCE( bs_equity__reserves , SUM( … ) )`` on rows 79 and 80. There is no coalesce op and none is
added, because printed-if-present-else-computed is ALREADY how every calculated line behaves
(services/rollups.py: "The printed figure is never discarded. It is what the divergence is measured
against") — the face shows the computed figure and the printed one becomes a calculated_mismatch
review card. A plain ``sum`` rollup therefore already means what the COALESCE was written to mean,
and a second op spelling the same behaviour is the trap that got ``weighted_sum`` deleted.
"""
from __future__ import annotations

import json
import pathlib
import sys

TPL = pathlib.Path("app/sample/templates/hkfrs_hk_china_template.json")
ONTOLOGY = pathlib.Path("app/sample/templates/hkfrs_hk_china_ontology.json")

# The two misspelt canonical keys, and what they become.
KEY_FIXES = {
    "bs_current_liabilities__cuurent_notes_payable":
        "bs_current_liabilities__current_notes_payable",
    "bs_current_liabilities__current_potion_of_long_term_debt":
        "bs_current_liabilities__current_portion_of_long_term_debt",
}

# Section ids, old -> new. Equity and current liabilities swap, which is why the rename is staged.
SECTION_RENAMES = {
    "bs_s3_equity": "bs_s5_equity",
    "bs_s5_current_liabilities": "bs_s3_current_liabilities",
}

# (canonical_key suffix, English label, zh label). Order is the order on screen.
NCA = [
    ("property_plant_and_equipment", "Property, Plant and Equipment", "物业、厂房及设备"),
    ("investment_properties", "Investment Properties", "投资物业"),
    ("right_of_use_assets", "Right-of-use assets", "使用权资产"),
    ("land_of_use_rights", "Land use rights", "土地使用权"),
    ("construction_in_progress", "Construction in progress", "在建工程"),
    ("properties_under_development", "Properties under development", "开发中物业"),
    ("goodwill", "Goodwill", "商誉"),
    ("other_intangible_assets", "Other Intangible assets", "其他无形资产"),
    ("intangible_assets_under_development", "Intangible assets under development", "在建无形资产"),
    ("investments_in_subsidiaries", "Investments in subsidiaries", "于子公司的投资"),
    ("interests_in_associates", "Interests in associates", "于联营公司的权益"),
    ("interests_in_joint_ventures", "Interests in joint ventures", "于合营企业的权益"),
    ("equity_investments_designated_at_fair_value_through_other_comprehensive_income",
     "Equity investments designated at fair value through other comprehensive income",
     "以公允价值计量且其变动计入其他综合收益的权益投资"),
    ("financial_assets_at_fair_value_through_profit_or_loss",
     "Financial assets at fair value through profit or loss",
     "以公允价值计量且其变动计入损益的金融资产"),
    ("other_non_current_financial_assets", "Other non-current financial assets",
     "其他非流动金融资产"),
    ("term_deposits", "Term Deposits", "定期存款"),
    ("prepayments_and_other_assets", "Prepayments and other assets", "预付款项及其他资产"),
    ("contract_in_progress", "Contract in progress", "在建合同"),
    ("deferred_income_tax_assets", "Deferred Income Tax Assets", "递延所得税资产"),
    ("others", "Others", "其他"),
]
CA = [
    ("inventories", "Inventories", "存货"),
    ("properties_under_development", "Properties under development", "开发中物业"),
    ("completed_properties_held_for_sale", "Completed properties held for sale", "持作销售的已完工物业"),
    ("trade_receivables", "Trade receivables", "应收账款"),
    ("contract_assets", "Contract assets", "合同资产"),
    ("prepayments_other_receivables_and_other_assets",
     "Prepayments, other receivables and other assets", "预付款项、其他应收款及其他资产"),
    ("due_from_related_parties", "Due from related parties", "应收关联方款项"),
    ("prepaid_income_tax", "Prepaid income tax", "预缴所得税"),
    ("financial_assets_at_fair_value_through_other_comprehensive_income",
     "Financial assets at fair value through other comprehensive income",
     "以公允价值计量且其变动计入其他综合收益的金融资产"),
    ("other_financial_assets", "Other Financial Assets", "其他金融资产"),
    ("pledged_deposits", "Pledged deposits", "已质押存款"),
    ("restricted_cash", "Restricted cash", "受限制现金"),
    ("bank_balances_other_than_cash_and_cash_equivalents",
     "Bank balances other than cash and cash equivalents", "除现金及现金等价物以外的银行存款"),
    ("cash_and_cash_equivalents", "Cash and cash equivalents", "现金及现金等价物"),
    ("others", "Others", "其他"),
]
CL = [
    ("current_trade_payables", "Trade payables", "应付账款"),
    ("current_notes_payable", "Notes payable", "应付票据"),
    ("contract_liabilities", "Contract liabilities", "合同负债"),
    ("other_payables_and_accruals", "Other payables and accruals", "其他应付款及预提费用"),
    ("due_to_related_parties", "Due to related parties", "应付关联方款项"),
    ("current_deferred_revenue", "Deferred Revenue", "递延收入"),
    ("current_lease_liabilities", "Lease Liabilities", "租赁负债"),
    ("current_borrowings", "Borrowings", "借款"),
    ("current_portion_of_long_term_debt", "Current portion of long term debt", "长期借款的即期部分"),
    ("other_current_financial_liabilities", "Other current financial liabilities",
     "其他流动金融负债"),
    ("current_income_tax_liabilities", "Income tax liabilities", "应付所得税"),
    ("others", "Others", "其他"),
]
NCL = [
    ("non_current_borrowings", "Borrowings", "借款"),
    ("non_current_bonds_payable", "Bonds payable", "应付债券"),
    ("non_current_notes_payable", "Notes Payable", "应付票据"),
    ("long_term_payables", "Long-term payables", "长期应付款"),
    ("non_current_lease_liabilities", "Lease liabilities", "租赁负债"),
    ("long_term_provisions", "Long-term provisions", "长期准备"),
    ("non_current_deferred_income", "Deferred income", "递延收益"),
    ("non_current_deferred_tax_liabilities_net", "Deferred tax liabilities (net)",
     "递延所得税负债（净额）"),
    ("others", "Others", "其他"),
]
# Equity is not a flat list: the two contributed-capital lines, then everything that rolls into
# reserves, then the attributable subtotal, then NCI.
EQ_HEAD = [
    ("share_capital", "Share capital", "股本"),
    ("other_equity_instruments", "Other equity instruments", "其他权益工具"),
]
# Treasury shares and shares held for award schemes belong here, negative: they are deductions from
# reserves, and reserves is where the spec puts them.
EQ_RESERVE_PARTS = [
    ("share_premium", "Share Premium", "股份溢价", "natural"),
    ("capital_reserve", "Capital reserve", "资本公积", "natural"),
    ("general_reserve", "General Reserve", "一般储备", "natural"),
    ("other_comprehensive_income_reserve", "Other comprehensive income reserve", "其他综合收益储备",
     "natural"),
    ("retained_earnings", "Retained earnings", "留存收益", "natural"),
    ("treasury_shares", "Treasury Shares", "库存股", "natural_negative"),
    ("shares_held_for_share_award_schemes", "Shares held for share award schemes",
     "为股份奖励计划持有的股份", "natural_negative"),
    ("others", "Others", "其他", "natural"),
]


def line(prefix: str, key: str, en: str, zh: str, sign: str = "natural") -> dict:
    ck = f"{prefix}__{key}"
    node = {"node_id": ck, "canonical_key": ck, "label": en, "role": "line",
            "label_i18n": {"en": en, "zh": zh}}
    if sign != "natural":
        node["sign"] = sign
    return node


def calc(ck: str, en: str, zh: str, op: str, children: list[str], role: str) -> dict:
    return {"node_id": ck, "canonical_key": ck, "label": en, "role": role,
            "label_i18n": {"en": en, "zh": zh}, "rollup": {"op": op, "children": children}}


def section(node_id: str, en: str, zh: str, children: list[dict]) -> dict:
    return {"node_id": node_id, "canonical_key": node_id, "label": en, "role": "header",
            "label_i18n": {"en": en, "zh": zh}, "children": children}


def build_balance_sheet() -> dict:
    p_nca, p_ca = "bs_non_current_assets", "bs_current_assets"
    p_cl, p_ncl, p_eq = "bs_current_liabilities", "bs_non_current_liabilities", "bs_equity"

    nca_lines = [line(p_nca, k, en, zh) for k, en, zh in NCA]
    nca_total = calc(f"{p_nca}__total_non_current_assets", "Total non-current assets",
                     "非流动资产总额", "sum", [c["canonical_key"] for c in nca_lines], "subtotal")

    ca_lines = [line(p_ca, k, en, zh) for k, en, zh in CA]
    ca_total = calc(f"{p_ca}__total_current_assets", "Total current assets", "流动资产总额",
                    "sum", [c["canonical_key"] for c in ca_lines], "subtotal")

    cl_lines = [line(p_cl, k, en, zh) for k, en, zh in CL]
    cl_total = calc(f"{p_cl}__total_current_liabilities", "Total current liabilities",
                    "流动负债总额", "sum", [c["canonical_key"] for c in cl_lines], "subtotal")

    ncl_lines = [line(p_ncl, k, en, zh) for k, en, zh in NCL]
    ncl_total = calc(f"{p_ncl}__total_non_current_liabilities", "Total non-current liabilities",
                     "非流动负债总额", "sum", [c["canonical_key"] for c in ncl_lines], "subtotal")

    eq_head = [line(p_eq, k, en, zh) for k, en, zh in EQ_HEAD]
    eq_reserve_parts = [line(p_eq, k, en, zh, sign) for k, en, zh, sign in EQ_RESERVE_PARTS]
    reserves = calc(f"{p_eq}__reserves", "Reserves", "储备", "sum",
                    [c["canonical_key"] for c in eq_reserve_parts], "subtotal")
    attributable = calc(f"{p_eq}__equity_attributable_to_owners",
                        "Equity attributable to owners of the Company", "本公司拥有人应占权益",
                        "sum", [c["canonical_key"] for c in eq_head] + [reserves["canonical_key"]],
                        "subtotal")
    nci = line(p_eq, "non_controlling_interests", "Non-controlling interests", "非控股权益")
    total_equity = calc(f"{p_eq}__total_equity", "Total equity", "权益总额", "sum",
                        [attributable["canonical_key"], nci["canonical_key"]], "subtotal")

    # The ladder, in presentation order.
    net_current = calc("bs_net_current_assets_liabilities", "Net current assets/(liabilities)",
                       "流动资产／（负债）净额", "diff",
                       [ca_total["canonical_key"], cl_total["canonical_key"]], "total")
    tal_cl = calc("bs_total_assets_less_current_liabilities",
                  "Total assets less current liabilities", "总资产减流动负债", "sum",
                  [nca_total["canonical_key"], net_current["canonical_key"]], "total")
    # NOT SUM(total_equity) — see the module docstring. This is the asset-side route, so the
    # equality with equity becomes a check that can actually fail.
    net_assets = calc("bs_net_assets", "NET ASSETS", "资产净值", "diff",
                      [tal_cl["canonical_key"], ncl_total["canonical_key"]], "total")
    total_liabilities = calc("bs_liabilities__total_liabilities", "Total liabilities", "负债总额",
                             "sum", [ncl_total["canonical_key"], cl_total["canonical_key"]],
                             "total")
    total_assets = calc("bs_total_assets", "Total Assets", "资产总额", "sum",
                        [nca_total["canonical_key"], ca_total["canonical_key"]], "total")
    total_eq_liab = calc("bs_total_equity_and_liabilities", "Total Equity and Liabilities",
                         "权益及负债总额", "sum",
                         [total_equity["canonical_key"], total_liabilities["canonical_key"]],
                         "total")

    sections = [
        section("bs_s1_non_current_assets", "Non-current assets", "非流动资产",
                nca_lines + [nca_total]),
        section("bs_s2_current_assets", "Current assets", "流动资产", ca_lines + [ca_total]),
        section("bs_s3_current_liabilities", "Current liabilities", "流动负债",
                cl_lines + [cl_total]),
        net_current, tal_cl,
        section("bs_s4_non_current_liabilities", "Non-current liabilities", "非流动负债",
                ncl_lines + [ncl_total]),
        net_assets,
        section("bs_s5_equity", "Equity", "权益",
                eq_head + eq_reserve_parts + [reserves, attributable, nci, total_equity]),
        total_liabilities, total_assets, total_eq_liab,
    ]

    # The footing, and only the footing. The other balance-sheet relations are the rulebook's, where
    # each carries a severity — see ``revise_validation`` and the module docstring.
    identities = [{"id": "bs_balances", "lhs": "bs_total_assets",
                   "rhs": {"op": "sum", "children": [total_eq_liab["canonical_key"]]}}]
    return {"type": "balance_sheet", "sections": sections, "identities": identities}


# --- the rulebooks -----------------------------------------------------------------------------

def _mapping_index(data: dict) -> dict[str, int]:
    return {m.get("canonical_key"): i for i, m in enumerate(data.get("mappings") or [])}


def _contract_assets() -> dict:
    """The new concept.

    This used to take a ``v2`` flag and write two different shapes, because two rulebook generations
    shipped: the thin file stated ``description``/``value_scope``/``extraction_mode``/``include`` on
    every concept and ``match_priority`` on none, the rich one the reverse, and a concept written in
    the other file's shape failed the invariants the suite holds. One rulebook ships now, so there is
    one shape and no way to pick the wrong one.
    """
    aliases = ["Contract assets", "Contract asset",
               "Amounts due from customers for contract work",
               "Gross amounts due from customers for contract works",
               "Unbilled receivables", "Accrued revenue"]
    shared = {
        "canonical_key": "bs_current_assets__contract_assets",
        "label": "Contract assets",
        "definition": ("HKFRS 15 right to consideration for work performed but not yet billed — "
                       "recognised revenue that has not become an unconditional receivable."),
    }
    tail = {
        "aliases": aliases,
        "aliases_i18n": {"en": aliases,
                         "zh": ["合同资产", "合約資產", "应收客户合同工程款", "未开票应收款"]},
        "confusable_with": ["bs_current_assets__trade_receivables",
                            "bs_current_liabilities__contract_liabilities"],
        "exclude_hints": ["liabilit", "负债", "負債", "payable", "应付"],
    }
    exclude = [
        "Trade receivables, which are unconditional rights to consideration and have their own "
        "concept.",
        "Contract costs capitalised as an asset under HKFRS 15.95, which are not contract assets.",
        "Contract liabilities, which are the mirror balance on the liability side.",
    ]
    return {**shared, "inherits": "bs_s2_current_assets", "match_priority": 64,
            "exclude": exclude, **tail}


def seed_contract_assets(data: dict) -> str | None:
    """Insert (or replace) the new concept directly after trade receivables."""
    entry = _contract_assets()
    mappings = data.setdefault("mappings", [])
    idx = _mapping_index(data)
    at = idx.get(entry["canonical_key"])
    if at is not None:
        if mappings[at] == entry:
            return None
        mappings[at] = entry
        return "contract assets rewritten to this file's shape"
    after = idx.get("bs_current_assets__trade_receivables")
    mappings.insert(len(mappings) if after is None else after + 1, entry)
    return "contract assets seeded"


def revise_keys(data: dict) -> int:
    """Rename the two misspelt keys.

    The first version of this also appended the old spelling to ``aliases``, meaning to keep a
    stored run's figure resolvable. That was wrong twice over. An ``aliases`` entry is a printed
    CAPTION the mapper matches a row's label against — no filing prints
    "bs_current_liabilities__cuurent_notes_payable", so the entry could never fire for its stated
    purpose, and it did change behaviour where it had no business to: it put a key-shaped string
    into the alias index, which shifted the notes-payable collision family and stopped a batch the
    suite expects to be REFUSED from being refused.

    There is no key-alias mechanism to use instead — the rulebook's own metadata notes say as much
    ("Rename with a key-alias table in v3"). So the honest consequence, stated rather than papered
    over: a run stored against the misspelt key resolves to no template node and its row reads as
    unmapped until the document is re-extracted. That loses a figure's PLACEMENT, never substitutes
    a wrong one, and re-extraction restores it.

    Renamed across the WHOLE document, for the same reason the section ids are: renaming only the
    ``canonical_key`` field left five ``confusable_with`` entries naming the misspelt keys, and
    ``confusable_with`` is what builds the collision families — so the notes-payable family lost its
    current-liabilities leaf and the current/non-current reroute the family exists for stopped
    firing, with the caption still landing on the right concept by another route. A relation that
    silently stops being exercised while the answer stays right is the hardest kind to notice.

    Prose that DOCUMENTS the two typos is deleted rather than renamed — the ``retained_defects``
    entry and one concept's definition both say the misspellings are kept deliberately, which after
    this is a claim the file contradicts. Renaming the key inside those sentences would leave a note
    reporting a typo in a key that no longer has one.
    """
    stale = [n for n in (data.get("metadata") or {}).get("retained_defects") or []
             if any(old.rsplit("__", 1)[1] in n for old in KEY_FIXES)]
    for note in stale:
        data["metadata"]["retained_defects"].remove(note)
    for m in data.get("mappings") or []:
        if (defn := m.get("definition")) and "legacy 'cuurent' typo" in defn:
            m["definition"] = defn.split(" Note: the canonical_key retains")[0]
    renamed, count = rename_outside_metadata(data, KEY_FIXES)
    data.clear()
    data.update(renamed)
    return count


def rename_outside_metadata(data: dict, mapping: dict[str, str]) -> tuple[dict, int]:
    """``_rename_everywhere``, with ``metadata`` held back — and the count of what moved.

    ``metadata.breaking_changes`` records renames by naming BOTH spellings ("X renamed to Y"), which
    is the whole value of the entry. Renaming inside it turns that into "Y renamed to Y" on the
    second run of the script, and the emptied sentence then differs from the one the script wants to
    append, so it appends a second copy: the file grows a corrupted note and a duplicate every time,
    and the script stops being idempotent. Held back rather than special-cased inside the walk,
    because the walk is deliberately blind to WHERE it is.
    """
    meta = data.pop("metadata", None)
    before = json.dumps(data, ensure_ascii=False)
    out = _rename_everywhere(data, mapping)
    if meta is not None:
        data["metadata"] = meta
        out["metadata"] = meta
    return out, sum(before.count(old) for old in mapping)


def sync_declared_count(data: dict) -> str | None:
    """Hold ``metadata.concept_count`` to the number of concepts actually declared.

    Seeding a concept without this leaves the rulebook stating its own size wrongly — the count is
    served on the ontology screen and in the download, so it is a printed number not derived from
    what it sits above.
    """
    meta = data.get("metadata")
    if not isinstance(meta, dict) or "concept_count" not in meta:
        return None
    actual = len(data.get("mappings") or [])
    if meta["concept_count"] == actual:
        return None
    was, meta["concept_count"] = meta["concept_count"], actual
    return f"metadata.concept_count {was} -> {actual}"


def _rename_everywhere(node, mapping: dict[str, str]):
    """Every dict KEY and every occurrence inside any string VALUE, renamed.

    Deliberately a whole-document walk rather than a list of the places a section id is allowed to
    appear. The first attempt renamed ``section_defaults`` keys, their ``section_scope`` and each
    concept's ``inherits`` — and missed ``residual_policy.section_scope``, two occurrences, which
    silently un-swept both residuals: ``stages/residual`` unions the concept's inherited scope with
    its policy's, and a residual scoped to two sections has no candidate set (prohibition 5,
    "never spans sections"), so every unclaimed current-liabilities row came back
    ``residual_ineligible`` instead. Enumerating the legal paths is a list that goes stale; walking
    the whole document cannot miss one.

    SUBSTRING, not exact match, because one ``section_disambiguation`` cites the id inside a
    sentence ("Section_scope (bs_s3_equity vs pl_s6 vs pl_s7) …"). Exact matching left that note
    naming a section that no longer exists — prose a reader would trust and which no schema check
    can catch. Safe as a substring: no id here is a prefix of another.
    """
    if isinstance(node, dict):
        return {mapping.get(k, k): _rename_everywhere(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [_rename_everywhere(v, mapping) for v in node]
    if isinstance(node, str):
        for old, new in mapping.items():
            node = node.replace(old, new)
    return node


def rename_sections(data: dict) -> tuple[dict, int]:
    """Follow the template's section-id renumbering through the whole rulebook.

    Staged through a temporary name because two ids SWAP: renaming ``bs_s3_equity`` to
    ``bs_s5_equity`` in one pass would collide with the ``bs_s5_current_liabilities`` still waiting
    to become ``bs_s3_current_liabilities``, and the second pass would then move both.
    """
    if not any(old in json.dumps(data) for old in SECTION_RENAMES):
        return data, 0
    staged = {old: f"__renaming__{old}" for old in SECTION_RENAMES}
    data = _rename_everywhere(data, staged)
    data = _rename_everywhere(data, {tmp: SECTION_RENAMES[old] for old, tmp in staged.items()})
    new_ids = set(SECTION_RENAMES.values())
    return data, sum(1 for m in data.get("mappings") or [] if m.get("inherits") in new_ids)


def sync_reserves_group(data: dict) -> str | None:
    """Hold the ``equity_reserves`` exclusivity group to the reserves rollup the template declares.

    Its components are DERIVED from ``EQ_RESERVE_PARTS`` rather than restated, because the group and
    the rollup are one list written twice: after the revision reserves absorbs share premium,
    treasury shares and shares held for award schemes, and a group still naming four of the eight
    would let three components be loaded ALONGSIDE the aggregate — the exact double-count it exists
    to prevent, silently, on the three it had stopped covering.
    """
    groups = ((data.get("global_rules") or {}).get("mutually_exclusive_groups")) or []
    group = next((g for g in groups if g.get("id") == "equity_reserves"), None)
    if group is None:
        return None
    want = [f"bs_equity__{k}" for k, *_ in EQ_RESERVE_PARTS]
    # Names the rollup, because the rollup is what enforces it. An earlier version of this note said
    # "the rulebook's bs_reserves_composition identity reports the disagreement" — an identity this
    # pass deliberately did NOT add, precisely because the rollup already asserts that sum. A note
    # citing a check that does not exist is the defect class the pass was closing.
    note = ("The template's bs_equity__reserves rollup lists all of these. Loading the aggregate and "
            "its components together double-counts, and that rollup is what reports the "
            "disagreement when a filing prints both.")
    if group.get("components") == want and group.get("note") == note:
        return None
    # Says which of the two moved. "components 8 -> 8" was the message when only the note changed,
    # which reads as work the run did not do.
    moved = ([f"components {len(group.get('components') or [])} -> {len(want)}"]
             if group.get("components") != want else []) + \
            (["note"] if group.get("note") != note else [])
    group["components"], group["note"] = want, note
    return f"equity_reserves group: {', '.join(moved)}"





# The relations the revised balance sheet makes checkable, as the rulebook spells them. Each is
# authored HERE and nowhere else: the template declares only the footing, so no fact enters the
# coverage denominator twice.
NEW_IDENTITIES = [
    {"id": "bs_derived_consistency",
     "expr": ("bs_net_assets = bs_total_assets "
              "- bs_current_liabilities__total_current_liabilities "
              "- bs_non_current_liabilities__total_non_current_liabilities"),
     "severity": "blocking",
     "note": ("An independent route to net assets: the ladder reaches it through net current "
              "assets, this reaches it through total assets, so a figure double-counted between "
              "the two sections breaks one and not the other. The equity attribution and the "
              "reserves composition are NOT here — the revised rollups on bs_equity__total_equity "
              "and bs_equity__reserves already assert exactly those two sums.")},
]

# Rulebook identities the revision DELETES, with the reason. ``bs_balance`` asserts
# ``bs_total_assets = bs_total_equity_and_liabilities`` — which is exactly the template's own
# ``bs_balances`` identity, so the footing was declared twice and counted twice in coverage. The
# template's copy is the one that survives: it holds under EVERY rulebook, including v1, which
# declares no validation block at all, and a template identity is blocking by default
# (``structural_checks.Relation.severity``), so nothing is lost by dropping the rulebook's.
DROP_IDENTITIES = {"bs_balance"}

# Relations already authored in the rulebook whose severity the revision changes, with the reason.
SEVERITY_CHANGES = {
    # The ladder is now the ROUTE to net assets, not a commentary on it: a break here means the
    # figure the balance check is run against was reached wrongly, which is not a "worth a look".
    "bs_capital_employed": "blocking",
}


def revise_validation(data: dict) -> list[str]:
    rules = data.get("validation")
    if not isinstance(rules, dict) or "identities" not in rules:
        return []                        # v1 declares no validation block; that is its shape
    idents = rules["identities"]
    notes = []
    for dropped in [i for i in idents if i.get("id") in DROP_IDENTITIES]:
        idents.remove(dropped)
        notes.append(f"identity {dropped['id']} dropped (the template declares this one)")
    at = {i.get("id"): n for n, i in enumerate(idents)}
    for ident in NEW_IDENTITIES:
        if ident["id"] in at:
            if idents[at[ident["id"]]] != ident:
                idents[at[ident["id"]]] = ident
                notes.append(f"identity {ident['id']} updated")
        else:
            idents.append(ident)
            notes.append(f"identity {ident['id']} added")
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
        if renamed := revise_keys(data):
            notes.append(f"{renamed} misspelt key(s) renamed")
        data, moved = rename_sections(data)
        if moved:
            notes.append(f"{moved} concept(s) follow the renumbered section ids")
        if seeded := seed_contract_assets(data):
            notes.append(seeded)
        if counted := sync_declared_count(data):
            notes.append(counted)
        if grouped := sync_reserves_group(data):
            notes.append(grouped)
        notes += revise_validation(data)
        if notes:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            out += [f"{path.name}: {n}" for n in notes]
    return out


def main() -> int:
    tpl = json.loads(TPL.read_text())
    for i, st in enumerate(tpl["statements"]):
        if st.get("type") == "balance_sheet":
            tpl["statements"][i] = build_balance_sheet()
            break
    else:
        print("no balance_sheet statement to replace")
        return 1
    TPL.write_text(json.dumps(tpl, ensure_ascii=False, indent=2) + "\n")

    bs = build_balance_sheet()
    rows = sum(1 + len(s.get("children") or []) if s.get("children") else 1
               for s in bs["sections"])
    print(f"balance sheet rewritten: {len(bs['sections'])} top-level nodes, {rows} screen rows")
    for note in revise_ontologies():
        print(f"  {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

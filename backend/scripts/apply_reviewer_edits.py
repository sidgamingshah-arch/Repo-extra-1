"""Apply the reviewer's rulebook edits: two deletions, four definition/alias changes, four sets of
exclude hints — and reorder the concepts into the order a statement reads.

Run with --check to report without writing.

THE POSITIONING CHANGE is the one the reviewer asked for by name ("gross profit should come [after]
cost of sales on P&L"). The TEMPLATE's order was already right; the ONTOLOGY's ``mappings`` array was
not, and the workbook's Concepts sheet is generated straight from that array. Gross profit sat 44th
among the profit-and-loss concepts, after the profit-attribution lines, with every top-level subtotal
dumped at the end and ``total_cost_of_sales`` filed after admin and R&D. So the array is sorted into
the template's own node order — the template is the authority on presentation, which makes this a
derived order rather than a hand-maintained second opinion.

THE TWO DELETIONS are subtotals, and removing a subtotal is not a data edit — it changes the shape of
the statement. Both are named by template nodes and by two rollups, so the arithmetic has to be
rewired or the numbers underneath them stop adding up:

    pl_gross_profit            = revenue + total_cost_of_sales
                               → revenue + cost_of_goods_sold + purchases_of_stock_in_trade
    total_operating_cost       = total_cost_of_sales + total_operating_expenses
                               → the eleven expense lines, flat

Sum-of-sums equals the flat sum, so every figure is preserved exactly; what changes is that two
intermediate rows stop being published. That is the reviewer's evident intent — the P&L then reads
revenue, cost of sales, GROSS PROFIT, operating expenses, total operating cost, EBIT, with no
redundant subtotal between cost of sales and the margin it produces.
"""
from __future__ import annotations

import argparse
import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent / "app/sample/templates"
ONTOLOGY = BASE / "hkfrs_hk_china_ontology.json"
TEMPLATE = BASE / "hkfrs_hk_china_template.json"

# ── deletions ──────────────────────────────────────────────────────────────────────────────────
DELETE = ["pl_expenses__total_cost_of_sales", "pl_expenses__total_operating_expenses"]

# What each deleted subtotal summed, so its parents can sum the same things directly.
EXPANDS: dict[str, list[str]] = {
    "pl_expenses__total_cost_of_sales": [
        "pl_expenses__cost_of_goods_sold",
        "pl_expenses__purchases_of_stock_in_trade",
    ],
    "pl_expenses__total_operating_expenses": [
        "pl_expenses__taxes_and_surcharges",
        "pl_expenses__selling_and_marketing_expenses",
        "pl_expenses__general_and_administrative_expenses",
        "pl_expenses__research_and_development_expenses",
        "pl_expenses__employee_benefits_expense",
        "pl_expenses__depreciation_and_amortisation_expense",
        "pl_expenses__other_operating_costs",
        "pl_expenses__other_expenses",
        "pl_expenses__others",
    ],
}

# ── content edits, keyed by canonical_key ──────────────────────────────────────────────────────
DEFINITIONS: dict[str, str] = {
    "bs_non_current_assets__goodwill": (
        "Goodwill is an intangible asset recorded when one company buys another for a price higher "
        "than the net fair market value of its identifiable assets and liabilities. It captures "
        "extra value like a strong brand, loyal customers, good employee relations, and secret "
        "technology."),
    "bs_non_current_assets__other_intangible_assets": (
        "All other intangible assets beyond goodwill and Intangible assets under development. Ensure "
        "if there is intangible asset on the face of the reported balance sheet which is not tagged, "
        "tag it here"),
}

# (key, alias to drop, alias to add) — a rename, not an addition, so the count stays put.
ALIAS_SWAPS: list[tuple[str, str, str]] = [
    ("bs_non_current_assets__intangible_assets_under_development",
     "Development costs", "Capitalised Software Development costs"),
]

# Added, not replaced: the hints already on these concepts work and removing them would lose live
# exclusions the reviewer did not ask to drop.
EXCLUDE_HINTS: dict[str, list[str]] = {
    "bs_non_current_assets__total_non_current_assets": [
        "Cash and cash equivalents", "Inventories",
        "Bank balances other than cash and cash equivalents", "Short term investments"],
    "bs_current_assets__others": ["Non-current Assets", "Long term"],
    "bs_non_current_liabilities__others": ["Current liability", "Trade payables", "Short term"],
    # The reviewer wrote "Loss / Gain of sale of asset" and "Loss / Gain on fair valuation". A hint is
    # a REGEX searched against the caption, so those read as literal strings containing " / " and
    # would never match a printed line however the case is handled. Translated to the fragments that
    # discriminate the same two families — a disposal result and a fair-value movement, both of which
    # belong to the exceptional-items section rather than this residual.
    "pl_expenses__others": ["Finance Cost", "Interest Expense", "disposal", "fair value"],
}


def flat_template_order(template: dict) -> list[str]:
    """Every canonical_key the template names, depth-first in presentation order."""
    order: list[str] = []

    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            key = node.get("canonical_key")
            if key:
                order.append(key)
            walk(node.get("children") or [])

    for statement in template.get("statements", []):
        walk(statement.get("sections", []))
    return order


def rewrite_rollups(template: dict, report: list[str]) -> None:
    """Replace a deleted subtotal inside every rollup that sums it, with what it summed."""
    def walk(nodes: list[dict]) -> None:
        for node in nodes:
            rollup = node.get("rollup") or {}
            children = rollup.get("children")
            if children:
                out: list[str] = []
                for child in children:
                    if child in EXPANDS:
                        out.extend(k for k in EXPANDS[child] if k not in out)
                        report.append(f"rollup {node.get('canonical_key')}: {child} -> "
                                      f"{len(EXPANDS[child])} components")
                    elif child not in out:
                        out.append(child)
                rollup["children"] = out
            walk(node.get("children") or [])

    for statement in template.get("statements", []):
        walk(statement.get("sections", []))


def drop_nodes(template: dict, report: list[str]) -> None:
    """Remove the deleted subtotals' own nodes from the tree."""
    def prune(nodes: list[dict]) -> list[dict]:
        kept: list[dict] = []
        for node in nodes:
            if node.get("canonical_key") in DELETE:
                report.append(f"template node removed: {node.get('canonical_key')}")
                continue
            if node.get("children"):
                node["children"] = prune(node["children"])
            kept.append(node)
        return kept

    for statement in template.get("statements", []):
        statement["sections"] = prune(statement.get("sections", []))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    onto = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    tpl = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    by_key = {c["canonical_key"]: c for c in onto["mappings"]}
    report: list[str] = []

    for key in [*DELETE, *DEFINITIONS, *EXCLUDE_HINTS, *(k for k, _, _ in ALIAS_SWAPS)]:
        if key not in by_key:
            print(f"FATAL unknown canonical_key: {key}")
            return 2

    # 1. content edits, before the deletions remove anything they might touch
    for key, text in DEFINITIONS.items():
        if by_key[key].get("definition") != text:
            by_key[key]["definition"] = text
            report.append(f"definition rewritten: {key}")
    for key, drop, add in ALIAS_SWAPS:
        aliases = by_key[key].setdefault("aliases", [])
        if drop in aliases:
            aliases[aliases.index(drop)] = add
            report.append(f"alias {drop!r} -> {add!r} on {key}")
        elif add not in aliases:
            aliases.append(add)
            report.append(f"alias {add!r} added to {key}")
    for key, hints in EXCLUDE_HINTS.items():
        current = by_key[key].get("exclude_hints") or []
        added = [h for h in hints if h not in current]
        if added:
            by_key[key]["exclude_hints"] = current + added
            report.append(f"exclude hints +{len(added)} on {key}")

    # 2. deletions — template arithmetic first, so the rewrite can still see what they summed
    rewrite_rollups(tpl, report)
    drop_nodes(tpl, report)
    onto["mappings"] = [c for c in onto["mappings"] if c["canonical_key"] not in DELETE]
    report += [f"concept deleted: {k}" for k in DELETE]

    # A dangling cross-reference is a claim about a concept that no longer exists.
    for concept in onto["mappings"]:
        for field in ("confusable_with", "never_sweep", "children_if_decomposed",
                      "expected_components"):
            values = concept.get(field)
            if isinstance(values, list) and any(v in DELETE for v in values):
                concept[field] = [v for v in values if v not in DELETE]
                report.append(f"dangling ref cleared: {concept['canonical_key']}.{field}")
        if concept.get("sole_component_of") in DELETE:
            concept["sole_component_of"] = None
            report.append(f"dangling ref cleared: {concept['canonical_key']}.sole_component_of")

    # 3. the positioning change
    order = {key: i for i, key in enumerate(flat_template_order(tpl))}
    before = [c["canonical_key"] for c in onto["mappings"]]
    # A concept the template does not name keeps its position relative to the last one that does, so
    # it stays beside the section it belongs to instead of being swept to the end.
    anchor, seq = -1, []
    for i, key in enumerate(before):
        if key in order:
            anchor = order[key]
        seq.append((anchor, i, key))
    onto["mappings"] = [by_key[k] for _a, _i, k in sorted(seq)]
    moved = sum(1 for a, b in zip(before, [c["canonical_key"] for c in onto["mappings"]]) if a != b)
    report.append(f"reordered into template presentation order: {moved} of {len(before)} rows moved")

    for line in report:
        print(" ", line)
    pl = [c["canonical_key"] for c in onto["mappings"] if c["canonical_key"].startswith("pl_")]
    gp = pl.index("pl_gross_profit") + 1
    cos = pl.index("pl_expenses__cost_of_goods_sold") + 1
    print(f"\n  P&L check: cost of sales at {cos}, gross profit at {gp} "
          f"({'CORRECT' if gp > cos else 'STILL WRONG'})")

    if args.check:
        print("\n--check: nothing written")
        return 0
    # Each file keeps the indent it ships with — the ontology is written at 1, the template at 2 —
    # so the diff shows the edit and not the whole file reflowed.
    ONTOLOGY.write_text(json.dumps(onto, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    TEMPLATE.write_text(json.dumps(tpl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {ONTOLOGY.name} and {TEMPLATE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

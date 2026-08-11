"""Computing the template's calculated lines.

A template marks each line `extracted` (read off the document) or `calculated` — a subtotal,
a total, a net figure — declared with a `rollup {op, children}` naming exactly which lines feed
it. This module evaluates those declarations.

Why the computed figure is the one that gets shown: a subtotal read off the page is a fourth
opinion, alongside the lines it is meant to be the sum of. When they disagree, showing the
printed one puts a number on the face that its own components contradict, and every total above
it inherits the contradiction. Showing the computed one makes the spread internally consistent by
construction — and turns the disagreement into a finding, which is what the review queue is for.

The printed figure is never discarded. It is what the divergence is measured against.

Evaluation is dependency-ordered because rollups nest: a statement total rolls up section
subtotals which roll up their own lines. A cycle (a template that declares A from B and B from A)
is reported rather than recursed into.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Ops a template may declare. `diff` is "first term minus the rest" — how a net figure is
# written (net current assets = current assets − current liabilities).
SUM = "sum"
DIFF = "diff"
WEIGHTED = "weighted_sum"


@dataclass
class Component:
    """One input to a calculated line, and the figure it contributed."""
    canonical_key: str
    label: str
    value: float | None
    sign: int = 1


@dataclass
class Calculated:
    """One calculated line's evaluation for a single (basis, period)."""
    canonical_key: str
    op: str
    components: list[Component] = field(default_factory=list)
    value: float | None = None
    # False when NO component had a figure, so there was nothing to compute from. Distinct from
    # a computed zero, and the difference matters: one is a gap, the other is an answer.
    computable: bool = False
    cycle: bool = False

    @property
    def formula(self) -> str:
        """The arithmetic as written, e.g. "12,800 + 2,150 + 3,410" or "19,564 − 8,120"."""
        joiner = " − " if self.op == DIFF else " + "
        parts = []
        for i, c in enumerate(self.components):
            if c.value is None:
                parts.append("—")
            else:
                parts.append(f"{abs(c.value):,.0f}" if i or c.value >= 0 else f"({abs(c.value):,.0f})")
        return joiner.join(parts)


def calculated_nodes(template_def: dict | None) -> dict[str, dict]:
    """canonical_key → the node, for every template line that declares a rollup."""
    out: dict[str, dict] = {}
    for stmt in (template_def or {}).get("statements", []):
        for sec in stmt.get("sections") or []:
            for node in [sec, *(sec.get("children") or [])]:
                key = node.get("canonical_key")
                # `rollup` is PRESENT and null on every non-calculated node once the template has
                # been through Pydantic, so `get("rollup", {})` hands back None, not the default.
                if key and (node.get("rollup") or {}).get("children"):
                    out[key] = node
    return out


def node_labels(template_def: dict | None, locale: str = "en") -> dict[str, str]:
    """canonical_key → the template's label for it, so a component can be named."""
    out: dict[str, str] = {}
    for stmt in (template_def or {}).get("statements", []):
        for sec in stmt.get("sections") or []:
            for node in [sec, *(sec.get("children") or [])]:
                key = node.get("canonical_key")
                if key:
                    out[key] = (node.get("label_i18n") or {}).get(locale) or node.get("label") \
                        or key
    return out


def evaluate_rows(template_def: dict | None, rows: list[dict], basis: str, period: str,
                  locale: str = "en") -> dict[str, "Calculated"]:
    """Evaluate the calculated lines directly from a run's extracted rows.

    The single entry point for both the statement API and the Excel export, so the workbook cannot
    disagree with the screen about what a subtotal is. Inputs are read through
    ``periods.concept_value``, which means a component's manual correction flows straight into
    every subtotal above it.
    """
    from app.services.periods import concept_value

    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = r.get("canonical_key")
        if key:
            groups.setdefault(key, []).append(r)

    def reported(key: str):
        return concept_value(groups.get(key, []), basis, period)

    return evaluate(template_def, reported, labels=node_labels(template_def, locale))


def _order(nodes: dict[str, dict]) -> tuple[list[str], set[str]]:
    """Calculated keys in dependency order, plus the keys caught in a cycle.

    A total that rolls up subtotals has to be evaluated after them, or it sums the printed
    figures it was supposed to replace.
    """
    order: list[str] = []
    state: dict[str, int] = {}          # 1 = visiting, 2 = done
    cyclic: set[str] = set()

    def visit(key: str, path: tuple[str, ...]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            cyclic.update(path[path.index(key):] if key in path else (key,))
            return
        state[key] = 1
        for child in (nodes[key].get("rollup") or {}).get("children") or []:
            if child in nodes:
                visit(child, path + (key,))
        state[key] = 2
        order.append(key)

    for key in nodes:
        visit(key, ())
    return order, cyclic


def evaluate(template_def: dict | None, reported, *, labels: dict[str, str] | None = None,
             prefer_calculated: bool = True) -> dict[str, Calculated]:
    """Evaluate every calculated line for one (basis, period).

    ``reported(key)`` returns the figure the DOCUMENT gives for a canonical key — the extracted
    value, or an analyst's manual override where there is one. ``prefer_calculated`` decides what
    a nested rollup sees when it reaches another calculated line: True feeds it the computed
    figure (so the whole tree is consistent with the leaves), False feeds it the printed one
    (which is what a reported-vs-computed comparison has to measure against).
    """
    nodes = calculated_nodes(template_def)
    names = labels or node_labels(template_def)
    order, cyclic = _order(nodes)
    out: dict[str, Calculated] = {}

    def figure(key: str) -> float | None:
        if prefer_calculated and key in out and out[key].computable:
            return out[key].value
        return reported(key)

    for key in order:
        rollup = nodes[key].get("rollup") or {}
        op = str(rollup.get("op") or SUM).lower()
        calc = Calculated(canonical_key=key, op=op, cycle=key in cyclic)
        if calc.cycle:
            out[key] = calc
            continue
        total: float | None = None
        for i, child in enumerate(rollup.get("children") or []):
            # In a `diff`, the first term is added and the rest subtracted.
            sign = -1 if (op == DIFF and i > 0) else 1
            val = figure(child)
            calc.components.append(Component(canonical_key=child, label=names.get(child, child),
                                             value=val, sign=sign))
            if val is not None:
                total = sign * val if total is None else total + sign * val
        calc.value = total
        calc.computable = total is not None
        out[key] = calc
    for key in cyclic:
        if key in out:
            out[key].cycle = True
    return out

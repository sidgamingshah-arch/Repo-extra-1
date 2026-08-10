"""Structural validation — the template's own arithmetic, used to catch mis-mapped values.

A label matcher can only ever be wrong about *which* concept a number belongs to, and no
amount of string evidence exposes that. Arithmetic does: if ``Gross profit != Revenue − Cost
of sales``, or a subtotal misses the sum of its declared children, then a value sits on the
wrong line or carries the wrong sign. This module evaluates the relations the TEMPLATE already
declares — ``rollup`` on subtotal/total nodes and statement-level ``identities`` — against the
mapped line items, so nothing about a particular framework is hardcoded here.

Two rules keep it honest on partial extractions (the normal case for a 270-page filing):

* A relation is evaluated only when the total AND every declared component was actually
  extracted and mapped for that (basis, period). Everything else is reported as *skipped* with
  a reason, never as a mismatch — a template subtotal lists every line the framework allows,
  so treating an absent child as zero would fail essentially every subtotal in the document.
* No value is derived, defaulted or back-filled to make a relation balance. A concept mapped
  twice with conflicting values is likewise refused rather than resolved by picking one.

Sums are signed, so the arithmetic holds whichever way the filing states expenses (a cost of
sales printed in parentheses arrives negative and simply adds). When a relation fails, the same
signed arithmetic can say whether flipping exactly one participant's sign would satisfy it —
reported as ``sign_suspect``, because a mis-signed value is a different fix from a mis-mapped
one. It is a hypothesis attached to the finding, never an adjustment.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.models import LineItem, RuleResult, StructuralReport
from app.schemas.template import TemplateDefinition
from app.services.reconcile import tolerance

# The tolerance convention used by DecompositionRule / the reconcile engine: an absolute floor
# with a relative band so large figures aren't held to sub-unit precision. Rollups carry no
# per-node tolerance; identities declare their own.
TOLERANCE_ABS = Decimal(1)
TOLERANCE_REL = Decimal("0.001")

Slot = tuple[str, str | None]          # (basis, period_label)


@dataclass(frozen=True)
class Relation:
    """One arithmetic relation read off the template: ``target = op(components)``."""

    id: str
    kind: str                          # rollup | identity
    statement: str
    target: str                        # canonical_key
    components: tuple[str, ...]        # canonical_keys
    op: str
    tol_abs: Decimal = TOLERANCE_ABS
    tol_rel: Decimal = TOLERANCE_REL


@dataclass
class MappedValues:
    """Mapped values per canonical_key per (basis, period), with the unusable keys called out."""

    values: dict[str, dict[Slot, Decimal]] = field(default_factory=dict)
    scales: dict[str, dict[Slot, Decimal]] = field(default_factory=dict)
    # Keys mapped more than once with conflicting values for the same slot. Choosing between
    # them would be a guess, so any relation touching one is not evaluated.
    ambiguous: set[str] = field(default_factory=set)

    def get(self, key: str, slot: Slot) -> Decimal | None:
        if key in self.ambiguous:
            return None
        return self.values.get(key, {}).get(slot)

    def slots(self, key: str) -> list[Slot]:
        if key in self.ambiguous:
            return []
        return list(self.values.get(key, {}))

    def scale(self, key: str, slot: Slot) -> Decimal:
        return self.scales.get(key, {}).get(slot, Decimal(1))


def _printed(ev) -> Decimal | None:
    """The value as extracted. Deliberately not ``reconciled``: the template's rollups describe
    the figures as presented, and the note→face subtraction is a different question."""
    v = ev.value if ev.value is not None else ev.value_raw
    return None if v is None else Decimal(v)


def collect_values(items: Iterable[LineItem]) -> MappedValues:
    out = MappedValues()
    for li in items:
        key = li.canonical_key
        if not key:
            continue
        for ev in li.values.values():
            val = _printed(ev)
            if val is None:
                continue
            slot: Slot = (ev.basis.value, ev.period_label)
            seen = out.values.setdefault(key, {})
            if slot in seen and seen[slot] != val:
                out.ambiguous.add(key)
                continue
            seen[slot] = val
            out.scales.setdefault(key, {})[slot] = ev.unit_ctx.scale_factor
    return out


def relations(template: TemplateDefinition) -> list[Relation]:
    """Every relation the template declares, as canonical keys.

    Rollup children and identity terms are node_ids (identities may also name a canonical_key),
    so both are resolved through the node table before anything is looked up by key.
    """
    key_of = {n.node_id: n.canonical_key for n in template.all_nodes()}
    known = template.all_canonical_keys()

    def resolve(term: str) -> str | None:
        return key_of.get(term) or (term if term in known else None)

    out: list[Relation] = []
    for st in template.statements:
        stype = st.type.value
        for node in template._walk(st.sections):
            if node.rollup is None or not node.rollup.children:
                continue
            children = [resolve(c) for c in node.rollup.children]
            if node.canonical_key is None or any(c is None for c in children):
                continue               # a dangling reference; the loader reports it on upload
            out.append(Relation(
                id=f"rollup:{node.canonical_key}", kind="rollup", statement=stype,
                target=node.canonical_key, components=tuple(children), op=node.rollup.op,
            ))
        for ident in st.identities:
            lhs, rhs = resolve(ident.lhs), [resolve(c) for c in ident.rhs.children]
            if lhs is None or any(c is None for c in rhs):
                continue
            out.append(Relation(
                id=f"identity:{ident.id}", kind="identity", statement=stype,
                target=lhs, components=tuple(rhs), op=ident.rhs.op,
                tol_abs=Decimal(str(ident.tolerance_abs)),
                tol_rel=Decimal(str(ident.tolerance_rel)),
            ))
    return out


# ``weighted_sum`` carries no weights in the schema, so it cannot be evaluated — a relation
# declaring it is reported as skipped rather than silently treated as a plain sum.
SUPPORTED_OPS = ("sum", "diff")


def _expected(op: str, parts: Sequence[Decimal]) -> Decimal:
    if op == "diff":
        return parts[0] - sum(parts[1:], Decimal(0))
    return sum(parts, Decimal(0))


def _sign_suspect(target: str, actual: Decimal, expected: Decimal,
                  parts: dict[str, Decimal], tol: Decimal) -> str | None:
    """The one participant whose sign, flipped, would satisfy the relation — or None.

    Only an unambiguous single candidate is named: with two equal-magnitude candidates the
    diagnosis would be a coin toss, and a wrong pointer is worse than none.
    """
    candidates = []
    if abs(-actual - expected) <= tol:
        candidates.append(target)
    for key, val in parts.items():
        if val and abs(actual - (expected - 2 * val)) <= tol:
            candidates.append(key)
    return candidates[0] if len(candidates) == 1 else None


def _scope(slot: Slot) -> str:
    return f"{slot[0]}/{slot[1] or '—'}"


def evaluate_structure(template: TemplateDefinition,
                       items: Iterable[LineItem]) -> StructuralReport:
    """Check every template relation whose participants were all extracted, per (basis, period)."""
    vals = collect_values(items)
    report = StructuralReport()

    for rel in relations(template):
        keys = (rel.target, *rel.components)
        if rel.op not in SUPPORTED_OPS:
            report.results.append(_skip(rel, [], "unsupported_op", {"op": rel.op}))
            continue
        blocked = sorted(k for k in keys if k in vals.ambiguous)
        if blocked:
            report.results.append(_skip(rel, [], "ambiguous_mapping", {"keys": blocked}))
            continue
        target_slots = sorted(vals.slots(rel.target), key=lambda s: (s[0], s[1] or ""))
        if not target_slots:
            report.results.append(_skip(rel, [], "target_not_extracted", {}))
            continue

        unmapped: dict[Slot, list[str]] = {}
        mixed: list[Slot] = []
        for slot in target_slots:
            missing = [c for c in rel.components if vals.get(c, slot) is None]
            if missing:
                unmapped[slot] = missing
                continue
            # Values are not unit-normalized, so a relation may only be evaluated where every
            # participant shares one scale — otherwise the sum compares thousands to millions.
            if len({vals.scale(k, slot) for k in keys}) > 1:
                mixed.append(slot)
                continue
            report.results.append(_check(rel, slot, vals))

        if unmapped:
            missing_keys = sorted({k for ks in unmapped.values() for k in ks})
            report.results.append(_skip(
                rel, list(unmapped), "components_not_mapped",
                {"missing": missing_keys, "missing_count": len(missing_keys),
                 "component_count": len(rel.components)}))
        if mixed:
            report.results.append(_skip(rel, mixed, "mixed_scale", {}))

    for res in report.failures():
        report.failed_assertions.append(
            f"{res.details['target']} does not equal {res.details['op']} of its "
            f"{len(res.details['components'])} template component(s) "
            f"({res.scope_key}): expected {res.expected}, got {res.actual}")
    return report


def _check(rel: Relation, slot: Slot, vals: MappedValues) -> RuleResult:
    parts = {c: vals.get(c, slot) for c in rel.components}
    actual = vals.get(rel.target, slot)
    expected = _expected(rel.op, list(parts.values()))
    diff = actual - expected
    tol = tolerance(expected, rel.tol_abs, rel.tol_rel)
    ok = abs(diff) <= tol
    return RuleResult(
        rule_id=rel.id, kind=rel.kind, scope_key=_scope(slot),
        status="pass" if ok else "fail",
        expected=expected, actual=actual, difference=diff,
        details={
            "target": rel.target, "components": list(rel.components), "op": rel.op,
            "statement": rel.statement, "basis": slot[0], "period_label": slot[1],
            "tolerance": str(tol),
            "component_values": {k: str(v) for k, v in parts.items()},
            "sign_suspect": (None if ok else _sign_suspect(rel.target, actual, expected,
                                                           parts, tol)),
        },
    )


def _skip(rel: Relation, slots: list[Slot], reason: str, extra: dict) -> RuleResult:
    """One 'not evaluable' row per relation+reason (not per period), so a partial extraction
    reports its coverage compactly instead of flooding the report."""
    return RuleResult(
        rule_id=rel.id, kind=rel.kind,
        scope_key=(";".join(_scope(s) for s in slots) if slots else "—"),
        status="skipped",
        details={"target": rel.target, "components": list(rel.components), "op": rel.op,
                 "statement": rel.statement, "reason": reason, **extra},
    )

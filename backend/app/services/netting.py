"""Face-line containment netting.

Some statements report a line inclusive of others — e.g. a cost of sales stated inclusive of
administrative and selling/marketing expenses. When the ontology declares such a containment,
the clean figure nets the contained lines out:

    net = target − Σ subtract + Σ add        (signed)

Signed arithmetic means it is correct whether expenses are stored as negatives (the usual case:
cost of sales −18,330, admin −1,710 → net −16,620) or as positives. It is deterministic,
non-destructive (the raw figure is preserved and the adjustment is revertable) and only applies
when the target and at least one contained line are actually present for that basis/period.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _num(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _value(rows_by_key: dict, key: str, basis: str, period: str) -> Decimal | None:
    row = rows_by_key.get(key)
    if not row:
        return None
    for v in row.get("values") or []:
        if (v.get("basis") or "consolidated") == basis and v.get("period_label") == period:
            return _num(v.get("value"))
    return None


def _label_for(rows_by_key: dict, key: str) -> str:
    row = rows_by_key.get(key) or {}
    return row.get("source_label") or key


def compute_netting(rows: list[dict], rules, *, basis: str = "consolidated",
                    period: str = "current") -> dict[str, dict]:
    """Per target key, the netted value + a human formula for one basis/period.

    ``rules`` is a list of NettingRule (or dicts with the same fields). Returns
    ``{target_key: {raw, net, formula, label, subtract, add}}`` only for rules whose target and
    at least one contained line are present — so a rule silently no-ops on a document that
    doesn't carry those lines."""
    by_key = {r.get("canonical_key"): r for r in rows if r.get("canonical_key")}
    out: dict[str, dict] = {}
    for rule in rules:
        target_key = getattr(rule, "target_key", None) or (rule.get("target_key") if isinstance(rule, dict) else None)
        sub_keys = getattr(rule, "subtract_keys", None)
        add_keys = getattr(rule, "add_keys", None)
        label = getattr(rule, "label", None)
        if isinstance(rule, dict):
            sub_keys = rule.get("subtract_keys", []) if sub_keys is None else sub_keys
            add_keys = rule.get("add_keys", []) if add_keys is None else add_keys
            label = rule.get("label", "") if label is None else label
        sub_keys = sub_keys or []
        add_keys = add_keys or []

        target = _value(by_key, target_key, basis, period)
        if target is None:
            continue
        subs = [(k, _value(by_key, k, basis, period)) for k in sub_keys]
        adds = [(k, _value(by_key, k, basis, period)) for k in add_keys]
        present_sub = [(k, v) for k, v in subs if v is not None]
        present_add = [(k, v) for k, v in adds if v is not None]
        if not present_sub and not present_add:
            continue

        net = target - sum((v for _, v in present_sub), Decimal(0)) \
            + sum((v for _, v in present_add), Decimal(0))
        terms = [_label_for(by_key, target_key)]
        terms += [f"− {_label_for(by_key, k)}" for k, _ in present_sub]
        terms += [f"+ {_label_for(by_key, k)}" for k, _ in present_add]
        out[target_key] = {
            "target_key": target_key,
            "raw": str(target),
            "net": str(net),
            "formula": " ".join(terms),
            "label": label or "",
            "subtract": [k for k, _ in present_sub],
            "add": [k for k, _ in present_add],
        }
    return out

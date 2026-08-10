"""Sign & unit normalization stage.

Produces the sign-normalized ``ExtractedValue.value`` from the printed ``value_raw`` using
signals the printed magnitude alone doesn't carry:

* ``Less:`` / ``Add:`` label cues — a line prefixed "Less:" is a deduction (negative);
  "Add:" is an addition (positive).
* the ontology's ``sign_rule.flip_if_label_matches`` regexes for the mapped concept — the
  ontology author's targeted sign corrections.

The printed-sign tier (parentheses / trailing minus) is already decoded into ``value_raw``
by ``services.numbers`` at extraction; this stage layers the label-driven corrections on top.
Values with no applicable cue keep ``value == value_raw``.
"""
from __future__ import annotations

import re
from decimal import Decimal

from app.core.models import DocumentModel
from app.core.models.line_item import UnitContext
from app.core.stage import PipelineContext

_LESS = re.compile(r"^\s*(less|deduct)\b|less:", re.IGNORECASE)
_ADD = re.compile(r"^\s*add\b|add:", re.IGNORECASE)

# "Amounts in ₹ crore", "(RMB'000)", "in thousands of USD", "figures in HK$ million" …
_UNIT_SCALE = {"thousand": Decimal(1_000), "lakh": Decimal(100_000), "lac": Decimal(100_000),
               "million": Decimal(1_000_000), "mn": Decimal(1_000_000),
               "crore": Decimal(10_000_000), "cr": Decimal(10_000_000),
               "billion": Decimal(1_000_000_000), "bn": Decimal(1_000_000_000)}
_UNIT_RE = re.compile(r"\b(thousands?|lakhs?|lacs?|millions?|mn|crores?|cr|billions?|bn)\b",
                      re.IGNORECASE)
_CCY = [("₹", "INR"), ("rs.", "INR"), ("inr", "INR"), ("hk$", "HKD"), ("hkd", "HKD"),
        ("rmb", "CNY"), ("cny", "CNY"), ("us$", "USD"), ("usd", "USD"), ("$", "USD"),
        ("€", "EUR"), ("eur", "EUR"), ("£", "GBP"), ("gbp", "GBP")]


def _detect_units(ctx: PipelineContext, fmt: str) -> UnitContext | None:
    """Detect a source scale + currency from a units declaration near the top of the document
    (e.g. "Amounts in ₹ crore"). Returns None when nothing is declared — the caller then treats
    values as reported rather than guessing a scale."""
    from app.services.derived import document_text

    try:
        pages = document_text(ctx.raw_bytes or b"", fmt)
    except Exception:  # noqa: BLE001
        return None
    text = " ".join(t for _, t in pages[:2]).lower()
    if not text:
        return None
    scale_word = None
    m = _UNIT_RE.search(text)
    if m:
        key = m.group(1).rstrip("s").lower()
        scale_word = key
    currency = next((code for tok, code in _CCY if tok in text), None)
    if scale_word is None and currency is None:
        return None
    scale = _UNIT_SCALE.get(scale_word, Decimal(1)) if scale_word else Decimal(1)
    return UnitContext(currency=currency or "INR", scale_factor=scale,
                       units_label=(scale_word or None))


class NormalizeStage:
    name = "normalize"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        # Source units/currency ("Amounts in ₹ crore") — recorded so the UI/export can convert
        # to a chosen presentation unit knowing the base (and never guessing when undeclared).
        detected = _detect_units(ctx, doc.fmt.value)
        if detected is not None:
            doc.unit_context = detected
            ctx.log(f"normalize:units={detected.units_label or 'as_reported'}/{detected.currency}")

        ontology = getattr(ctx, "ontology", None)
        sign_by_key: dict[str, list] = {}
        if ontology is not None:
            for m in getattr(ontology, "mappings", []) or []:
                pats = getattr(getattr(m, "sign_rule", None), "flip_if_label_matches", None) or []
                if pats:
                    sign_by_key[m.canonical_key] = [re.compile(p, re.IGNORECASE) for p in pats]

        changed = 0
        for li in doc.line_items:
            label = li.source_label or ""
            less = bool(_LESS.search(label))
            add = bool(_ADD.search(label))
            flips = sign_by_key.get(li.canonical_key or "", [])
            flip = any(rx.search(label) for rx in flips)
            if not (less or add or flip):
                continue
            for ev in li.values.values():
                raw = ev.value_raw
                if raw is None:
                    continue
                v = raw
                if less:
                    v = -abs(raw)
                elif add:
                    v = abs(raw)
                if flip:
                    v = -v
                if v != ev.value:
                    ev.value = v
                    changed += 1

        ctx.log(f"normalize:sign_adjusted={changed}")
        return doc

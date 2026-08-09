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

from app.core.models import DocumentModel
from app.core.stage import PipelineContext

_LESS = re.compile(r"^\s*(less|deduct)\b|less:", re.IGNORECASE)
_ADD = re.compile(r"^\s*add\b|add:", re.IGNORECASE)


class NormalizeStage:
    name = "normalize"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
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

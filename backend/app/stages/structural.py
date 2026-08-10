"""Structural validation stage — runs the template's arithmetic over the mapped line items.

Wires ``services.structural_checks`` (pure, unit-tested) to the document model: it stores the
report on ``doc.structural`` and flags every line item and value that participates in a failed
relation, so a mis-mapped or mis-signed number reaches the review queue even though its label
matched perfectly.

It runs after the confidence stage on purpose: that stage assigns ``validation`` outright for
the balance identity, while a structural failure may only *lower* an existing signal — so it
has to see the final value, not be overwritten by it.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext
from app.services.structural_checks import evaluate_structure

FLAG = "structural_mismatch"
_VALIDATION_CAP = 0.5     # same weight as a note that doesn't tie: a failed check dominates


class StructuralStage:
    name = "structural"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        template = getattr(ctx, "template", None)   # attribute set by services.documents
        if template is None or not doc.line_items:
            ctx.log("structural:skipped(no template or no line items)")
            return doc

        report = evaluate_structure(template, doc.line_items)
        doc.structural = report

        # (canonical_key, basis, period) triples that took part in a failed relation — the
        # total and its components alike, since the arithmetic cannot say which one is wrong.
        involved: set[tuple[str, str, str | None]] = set()
        for res in report.failures():
            d = res.details
            for key in (d["target"], *d["components"]):
                involved.add((key, d["basis"], d["period_label"]))

        flagged = 0
        for li in doc.line_items:
            if not li.canonical_key:
                continue
            hit = False
            for ev in li.values.values():
                if (li.canonical_key, ev.basis.value, ev.period_label) not in involved:
                    continue
                hit = True
                flagged += 1
                ev.confidence.flags.append(FLAG)
                prior = ev.confidence.validation
                ev.confidence.validation = min(_VALIDATION_CAP,
                                               prior if prior is not None else 1.0)
            if hit:
                li.confidence.flags.append(FLAG)

        ctx.log(f"structural:evaluated={len(report.evaluated())} "
                f"failed={len(report.failures())} not_evaluable={len(report.skipped())} "
                f"flagged_values={flagged}")
        return doc

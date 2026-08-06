"""Reconciliation stage (§20) — applies the note→face subtraction.

For each ``FaceNoteLink``, per (basis, period), computes the reconciled face value via
``services.reconcile.reconcile_face`` (pure, tested) and records a
``ReconciliationEntry``. Failed tolerance checks / negative residuals are surfaced for
the review queue.

Scaffold: iterates links once they exist (built by ``link_notes``); the per-value
wiring is TODO but the arithmetic core is complete and unit-tested.
"""
from __future__ import annotations

from app.core.models import DocumentModel, ReconciliationReport
from app.core.stage import PipelineContext


class ReconcileStage:
    name = "reconcile"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        report = ReconciliationReport()
        if not doc.links:
            ctx.log("reconcile:no_links")
            return doc
        # TODO: for each link × (basis, period): gather note details that map to a
        #       distinct template line, call services.reconcile.reconcile_face, write
        #       reconciled back onto the face ExtractedValue, append a report entry.
        ctx.log(f"reconcile:links={len(doc.links)}")
        return doc

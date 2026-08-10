"""Reconciliation stage (§20) — applies the note→face subtraction.

For each ``FaceNoteLink``, per (basis, period), it subtracts the note detail lines that are
*themselves* ingested as distinct template lines (avoiding double counting), writes the
reconciled figure onto the face ``ExtractedValue.reconciled`` (always derived from the raw
face value, so re-running is idempotent), and records a ``ReconciliationEntry``. It also
checks that the FULL note total ties back to the face figure within tolerance; a residual
outside tolerance (or a negative reconciled value) is flagged for the review queue.

The arithmetic core lives in ``services.reconcile`` (pure, unit-tested); this stage wires it
to the document model.
"""
from __future__ import annotations

from decimal import Decimal

from app.core.models import DocumentModel
from app.core.models.enums import LineRole
from app.core.models.reports import ReconciliationEntry, ReconciliationReport
from app.core.stage import PipelineContext
from app.services.reconcile import NoteDetail, ReconcileInput, reconcile_face


def _note_value(item, basis, period_label) -> Decimal | None:
    """A note detail item's value for one (basis, period)."""
    for ev in item.values.values():
        if ev.basis == basis and ev.period_label == period_label:
            return ev.value if ev.value is not None else ev.value_raw
    return None


class ReconcileStage:
    name = "reconcile"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        report = ReconciliationReport()
        if not doc.links:
            doc.reconciliation = report
            ctx.log("reconcile:no_links")
            return doc

        face_by_id = {li.id: li for li in doc.line_items}
        note_by_id = {nt.id: nt for nt in doc.notes}
        # Canonical keys that appear as their OWN face line — a note detail mapping to one of
        # these is double-counted and must be subtracted from the aggregate.
        distinct_face_keys = {li.canonical_key for li in doc.line_items if li.canonical_key}

        applied = 0
        for link in doc.links:
            face = face_by_id.get(link.face_item_id)
            note = note_by_id.get(link.notes_table_id)
            if face is None or note is None:
                continue
            for ev in face.values.values():
                raw = ev.value if ev.value is not None else ev.value_raw
                if raw is None:
                    continue
                details: list[NoteDetail] = []
                for it in note.items:
                    if it.role in (LineRole.SUBTOTAL, LineRole.TOTAL):
                        continue                      # a note's own subtotal isn't a detail
                    dv = _note_value(it, ev.basis, ev.period_label)
                    if dv is None:
                        continue
                    maps = bool(it.canonical_key and it.canonical_key in distinct_face_keys
                                and it.canonical_key != face.canonical_key)
                    details.append(NoteDetail(item_id=str(it.id), value=Decimal(dv),
                                              maps_to_distinct_template_line=maps))
                if not details:
                    continue
                out = reconcile_face(ReconcileInput(
                    face_item_id=str(face.id), note_number=link.note_number,
                    raw_face_value=Decimal(raw), details=details))
                ev.reconciled = out.reconciled
                report.entries.append(ReconciliationEntry(
                    face_item_id=str(face.id), note_number=link.note_number,
                    basis=ev.basis.value, period_label=ev.period_label,
                    raw_face=out.raw_face, subtracted=out.subtracted, reconciled=out.reconciled,
                    residual=out.residual, within_tolerance=out.within_tolerance,
                    relationship=link.relationship.value))
                if not out.within_tolerance:
                    report.failed_assertions.append(
                        f"Note {link.note_number} does not tie to "
                        f"{face.canonical_key or face.source_label} "
                        f"({ev.basis.value}/{ev.period_label}): residual {out.residual}")
                applied += 1

        doc.reconciliation = report
        ctx.log(f"reconcile:entries={len(report.entries)} failed={len(report.failed_assertions)}")
        return doc

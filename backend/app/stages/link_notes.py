"""Note-linking stage — builds ``FaceNoteLink``s.

For each face ``LineItem`` with ``note_refs``, looks up the referenced note and
validates the link by amount (note total vs face value within tolerance), classifying
it as ONE_TO_ONE / NOTE_SPLITS_TO_MANY_FACE / MANY_NOTES_TO_ONE_FACE / PARTIAL. The
links produced here are consumed by the reconcile stage (§20).

Scaffold: the amount-validation + classification is TODO; the data structures and the
reconciliation arithmetic it feeds are implemented (services/reconcile.py).
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext


class LinkNotesStage:
    name = "link_notes"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        if not doc.line_items or not doc.notes:
            ctx.log("link_notes:skipped")
            return doc
        # TODO: build NoteIndex {note_number -> NotesTable}; for each face item with
        #       note_refs, create a FaceNoteLink, validate by amount, classify.
        ctx.log("link_notes:todo")
        return doc

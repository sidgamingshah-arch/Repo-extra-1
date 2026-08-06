"""Row/value extraction stage.

Turns reconstructed ``Table`` rows into ``LineItem``s: parses values (locale-aware,
via ``services.numbers``), detects the two-level Consolidated/Standalone column
header, captures note references, and records provenance for every value.

Scaffold: the row-walking logic is TODO (depends on the reconstruct stage output);
the number-parsing and note-ref primitives it will use already exist.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext


class ExtractStage:
    name = "extract"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        if not doc.tables:
            ctx.log("extract:no_tables")
            return doc
        # TODO: for each table row → LineItem with values keyed by (basis, period),
        #       note_refs, unit context, provenance (bbox). Uses services.numbers.
        ctx.log(f"extract:tables={len(doc.tables)}")
        return doc

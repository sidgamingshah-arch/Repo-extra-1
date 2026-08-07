"""Row/value extraction stage.

Turns reconstructed ``Table`` rows into ``LineItem``s: parses values (locale-aware,
via ``services.numbers``), detects the two-level Consolidated/Standalone column
header, captures note references, and records provenance for every value.

Scaffold: the row-walking logic is TODO (depends on the reconstruct stage output);
the number-parsing and note-ref primitives it will use already exist.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.models.enums import DocFormat
from app.core.stage import PipelineContext


class ExtractStage:
    name = "extract"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        # Excel: read values + exact cell provenance straight from the workbook (no OCR/LLM).
        if doc.fmt in (DocFormat.XLSX, DocFormat.XLS) and ctx.raw_bytes:
            from app.services.excel_extract import extract_workbook

            try:
                items = extract_workbook(ctx.raw_bytes, document_id=doc.content_hash)
            except Exception as exc:  # openpyxl missing / unreadable → surfaced, not fatal
                ctx.log(f"extract:xlsx_failed:{exc}")
                return doc
            doc.line_items.extend(items)
            ctx.log(f"extract:xlsx_line_items={len(items)}")
            return doc

        if not doc.tables:
            ctx.log("extract:no_tables")
            return doc
        # TODO (PDF native/scanned): for each table row → LineItem with values keyed by
        #       (basis, period), note_refs, unit context, provenance (bbox).
        ctx.log(f"extract:tables={len(doc.tables)}")
        return doc

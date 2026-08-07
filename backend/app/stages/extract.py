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

        # PDF: native pages via the PyMuPDF text layer, scanned pages via the OCR port —
        # both converge on shared word→line-item reconstruction with bbox provenance.
        if doc.fmt == DocFormat.PDF and ctx.raw_bytes:
            from app.services.pdf_extract import extract_pdf

            extract_pdf(ctx.raw_bytes, doc, ctx)
            return doc

        ctx.log("extract:no_source_bytes")
        return doc

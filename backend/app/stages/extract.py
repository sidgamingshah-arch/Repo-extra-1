"""Row/value extraction stage.

Reconstructs tables and turns their rows into ``LineItem``s in one step, per source:

* Excel — values + exact cell provenance read straight from the workbook.
* Native PDF — the PyMuPDF text layer feeds the shared ``row_reconstruct`` logic
  (locale-aware value parsing via ``services.numbers``, two-level
  Consolidated/Standalone header detection, note-ref capture, bbox provenance).
* Scanned PDF / image — the OCR port produces words that feed the same reconstruction.

Notes pages route to note-detail tables; every other in-scope page yields face line items.
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

        # Standalone image (scanned page as PNG/JPG/TIFF): OCR the bytes directly.
        if doc.fmt == DocFormat.IMAGE and ctx.raw_bytes:
            from app.services.pdf_extract import extract_image

            extract_image(ctx.raw_bytes, doc, ctx)
            return doc

        ctx.log("extract:no_source_bytes")
        return doc

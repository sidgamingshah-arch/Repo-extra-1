"""Page-classification stage (face / notes / other).

Layered approach: cheap lexical/layout heuristics first, LLM classifier only for
low-confidence tie-breaks. A dependency-free lexical heuristic is implemented here as
a starting point; the layout + LLM layers are TODO (see docs/architecture).
"""
from __future__ import annotations

import re

from app.core.models import DocumentModel, PageKind
from app.core.stage import PipelineContext

_FACE_TITLES = {
    PageKind.FACE: [
        r"balance sheet", r"statement of financial position",
        # P&L is titled many ways — "profit or loss" is the canonical IFRS/HKFRS phrasing.
        r"statement of profit (and|&|or) loss", r"profit or loss", r"income statement",
        r"statement of operations",
        r"(statement of )?comprehensive income",
        r"cash flow", r"statement of cash flows", r"changes in equity",
    ],
}
_NOTES_TITLES = [r"notes to the (financial|consolidated) statements",
                 r"significant accounting policies", r"^note\s*\d+"]


class ClassifyStage:
    name = "classify"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        data = ctx.raw_bytes
        if not data or doc.fmt.value != "pdf":
            return doc
        try:
            import fitz
        except ImportError:
            return doc
        try:
            pdf = fitz.open(stream=data, filetype="pdf")
        except Exception:  # noqa: BLE001
            return doc

        for page_src in doc.pages:
            if page_src.index >= len(pdf):
                continue
            text = (pdf[page_src.index].get_text("text") or "").lower()
            if any(re.search(rx, text) for rx in _NOTES_TITLES):
                page_src.kind = PageKind.NOTES
                page_src.classification_confidence = 0.7
            elif any(re.search(rx, text) for rx in _FACE_TITLES[PageKind.FACE]):
                page_src.kind = PageKind.FACE
                page_src.classification_confidence = 0.7
            else:
                page_src.kind = PageKind.OTHER
                page_src.classification_confidence = 0.4
        pdf.close()
        ctx.log(f"classify:face={len(doc.face_pages())} notes={len(doc.notes_pages())}")
        # TODO: layout features (note column, numeric column pairs) + LLM tie-break.
        return doc

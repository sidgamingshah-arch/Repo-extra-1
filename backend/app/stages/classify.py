"""Page-classification stage (face / notes / other).

Layered lexical/layout heuristics (LLM tie-break is a documented future layer). Two
properties matter for real annual reports, where the notes run for many pages:

* **Title-anchored FACE.** A page is a statement *face* only when a face title appears
  near the TOP of the page — not merely because a phrase like "profit or loss" or
  "cash flow" occurs somewhere in the body. Notes frequently mention those phrases, so
  matching anywhere misclassifies note pages as face (and then their note tables are
  never extracted).
* **Sticky NOTES section.** The face statements come first, then a "Notes to the
  financial statements" page, then many continuation pages headed like "14. Cash and
  cash equivalents" with no "notes" banner. Once the notes section begins, subsequent
  financial pages stay NOTES unless a new face title clearly leads the page — so the
  whole notes section is captured, not just its first page.
"""
from __future__ import annotations

import re

from app.core.models import DocumentModel, PageKind
from app.core.stage import PipelineContext

# Face-statement titles (IFRS/HKFRS/Ind-AS phrasings). Matched only against the top of a page.
_FACE_TITLES = [
    r"balance sheet", r"statement of financial position",
    r"statement of profit (and|&|or) loss", r"profit or loss", r"income statement",
    r"statement of operations", r"(statement of )?comprehensive income",
    r"statement of cash ?flows?", r"cash flow statement",
    r"statement of changes in equity", r"changes in equity",
]
# Explicit markers that the notes section has begun.
_NOTES_HEADERS = [
    r"notes? to the (financial|consolidated|unconsolidated|standalone) statements",
    r"notes forming part of the (financial|consolidated) statements",
    r"significant accounting policies", r"material accounting policies",
]
# A numbered note heading at the top of a page, e.g. "14. Cash and cash equivalents",
# "Note 14 —", "14 Trade receivables". Requires text after the number so bare figures
# (a column of amounts) don't trip it.
_NUMBERED_HEADING = re.compile(r"(?m)^\s*(note\s*)?\d{1,2}[.)]?\s+[A-Za-z]{3,}")
_NOTE_REF = re.compile(r"\bnotes?\s*\d{1,2}\b", re.I)
_DIGIT = re.compile(r"\d")


def _head(text: str, lines: int = 15, chars: int = 800) -> str:
    """The top of a page — the first few non-empty lines, capped — where a statement title
    would appear. Titles are matched here so a mid-page mention doesn't count."""
    kept: list[str] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln:
            kept.append(ln)
        if len(kept) >= lines:
            break
    return "\n".join(kept)[:chars].lower()


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

        notes_started = False
        for page_src in doc.pages:
            if page_src.index >= len(pdf):
                continue
            text = pdf[page_src.index].get_text("text") or ""
            head = _head(text)
            low = text.lower()

            face_title_at_top = any(re.search(rx, head) for rx in _FACE_TITLES)
            notes_header = any(re.search(rx, low) for rx in _NOTES_HEADERS)
            numbered_heading = bool(_NUMBERED_HEADING.search(text))
            note_refs = len(_NOTE_REF.findall(low))
            has_numbers = bool(_DIGIT.search(text))

            # The notes section begins at an explicit header, or at a numbered note heading
            # that also references notes (so a lone numbered list elsewhere doesn't start it).
            if notes_header or (numbered_heading and note_refs > 0):
                notes_started = True

            if notes_started:
                # Sticky: stay in NOTES unless a new face statement clearly leads the page
                # (a face title at the very top, with no note heading/reference).
                if face_title_at_top and not numbered_heading and note_refs == 0:
                    kind, conf = PageKind.FACE, 0.7
                elif has_numbers or numbered_heading or note_refs or notes_header:
                    kind, conf = PageKind.NOTES, 0.75 if notes_header else 0.6
                else:
                    kind, conf = PageKind.OTHER, 0.4
            elif face_title_at_top:
                kind, conf = PageKind.FACE, 0.7
            else:
                kind, conf = PageKind.OTHER, 0.4

            page_src.kind = kind
            page_src.classification_confidence = conf

        pdf.close()
        ctx.log(f"classify:face={len(doc.face_pages())} notes={len(doc.notes_pages())}")
        return doc

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

# Face-statement titles. IFRS/HKFRS/Ind-AS English phrasings, plus the Simplified/Traditional
# Chinese titles HK-listed PRC entities use (often bilingual filings). Matched only at the top.
_FACE_TITLES = [
    r"balance sheet", r"statement of financial position",
    r"statement of profit (and|&|or) loss", r"profit or loss", r"income statement",
    r"statement of operations", r"(statement of )?comprehensive income",
    r"statement of cash ?flows?", r"cash flow statement",
    r"statement of changes in equity", r"changes in equity",
    # Chinese: 资产负债表 / 财务状况表, 利润表/损益表, 综合(全面)收益表, 现金流量表, 权益变动表
    r"资产负债表", r"資產負債表", r"财务状况表", r"財務狀況表",
    r"利润表", r"利潤表", r"损益表", r"損益表",
    r"综合(收益|损益)表", r"全面(收益|損益)表", r"綜合(收益|損益)表",
    r"现金流量表", r"現金流量表", r"权益变动表", r"權益變動表",
]
# Explicit markers that the notes section has begun (English + Chinese).
_NOTES_HEADERS = [
    r"notes? to the (financial|consolidated|unconsolidated|standalone) statements",
    r"notes forming part of the (financial|consolidated) statements",
    r"significant accounting policies", r"material accounting policies",
    r"(合并|合併|综合|綜合)?财务报表附注", r"(合并|合併|綜合)?財務報表附註",
    r"重要会计政策", r"重要會計政策", r"主要会计政策", r"主要會計政策",
]
# A numbered note heading at the top of a page, e.g. "14. Cash and cash equivalents",
# "Note 14 —", "14 Trade receivables", or the Chinese "14 现金及现金等价物". Requires text
# after the number (Latin or CJK) so bare figures (a column of amounts) don't trip it.
_NUMBERED_HEADING = re.compile(r"(?m)^\s*(note\s*)?\d{1,2}[.)、]?\s+[A-Za-z一-鿿]{2,}")
# A note reference within a page: "note 14" / "notes 14" or Chinese "附注14" / "附註14".
_NOTE_REF = re.compile(r"\bnotes?\s*\d{1,2}\b|附註?\s*\d{1,2}", re.I)
_DIGIT = re.compile(r"\d")


def _looks_like_heading(line: str) -> bool:
    """A statement title is a short heading line — not a sentence. Auditor's-report prose such
    as 'We audited the statement of profit or loss …' mentions face phrases but is long and ends
    like a sentence, so it must not count as a title."""
    s = line.strip()
    if not s or len(s) > 72:
        return False
    if s.endswith((".", ";", ":", ",", "。", "，", "、", "；", "：")):
        return False
    return sum(ch.isdigit() for ch in s) <= 8   # a heading, not a row of figures


def _face_title_at_top(text: str) -> bool:
    """True when a face-statement title appears as a heading-like line among the first few
    non-empty lines — anchored to the top AND shaped like a title, so a mid-page or in-sentence
    mention (common in note prose and the auditor's report) never counts."""
    seen = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        seen += 1
        if seen > 6:
            break
        if _looks_like_heading(line) and any(re.search(rx, line.lower()) for rx in _FACE_TITLES):
            return True
    return False


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
        seen_face = False       # a face statement has appeared → the notes come after it
        for page_src in doc.pages:
            if page_src.index >= len(pdf):
                continue
            text = pdf[page_src.index].get_text("text") or ""
            low = text.lower()

            face_title_at_top = _face_title_at_top(text)
            notes_header = any(re.search(rx, low) for rx in _NOTES_HEADERS)
            numbered_heading = bool(_NUMBERED_HEADING.search(text))
            note_refs = len(_NOTE_REF.findall(low))
            has_numbers = bool(_DIGIT.search(text))

            # The notes section begins at an explicit header, or at a numbered note heading that
            # either back-references a note OR follows the face statements — real reports open the
            # notes with "1 General information" / "1 Basis of preparation", which carries no note
            # reference and (in some filings) no "Notes to…" banner. A face page never starts it.
            if not face_title_at_top and (
                notes_header or (numbered_heading and (note_refs > 0 or seen_face))
            ):
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
                seen_face = True
            else:
                kind, conf = PageKind.OTHER, 0.4

            page_src.kind = kind
            page_src.classification_confidence = conf

        pdf.close()
        ctx.log(f"classify:face={len(doc.face_pages())} notes={len(doc.notes_pages())}")
        return doc

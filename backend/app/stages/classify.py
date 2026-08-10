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
# Which face statement a title names. Ordered: the more specific title wins, because
# "statement of profit or loss AND OTHER COMPREHENSIVE INCOME" also contains a bare
# "comprehensive income", and a changes-in-equity title contains the word "equity" only.
# Knowing the statement lets ontology mapping reject concepts from a different statement.
_STATEMENT_TITLES: list[tuple[str, list[str]]] = [
    ("changes_in_equity", [r"statement of changes in equity", r"changes in equity",
                           r"权益变动表", r"權益變動表", r"股東權益變動表", r"股东权益变动表"]),
    ("cash_flow", [r"statement of cash ?flows?", r"cash ?flow statement",
                   r"现金流量表", r"現金流量表"]),
    ("balance_sheet", [r"balance sheet", r"statement of financial position",
                       r"资产负债表", r"資產負債表", r"财务状况表", r"財務狀況表"]),
    ("profit_and_loss", [r"statement of profit (and|&|or) loss", r"profit or loss",
                         r"income statement", r"statement of operations",
                         r"(statement of )?comprehensive income",
                         r"利润表", r"利潤表", r"损益表", r"損益表",
                         r"综合(收益|损益)表", r"綜合(收益|損益)表",
                         r"全面(收益|損益)表"]),
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


# A page's running header repeats on every page of a real annual report (company name /
# "Annual Report YYYY" / the Chinese equivalent). We skip those lines so a statement title is
# read from the actual page heading beneath them, not from the running chrome.
_RUNNING_HEADER = re.compile(r"annual report|interim report|年報|年度報告|中期報告", re.I)
# Contexts where a face phrase is NOT a statement face: the highlights/summary pages and the
# five-year summary that bracket the real statements.
_SUMMARY_CTX = re.compile(r"summary|highlights?|five[\s-]?year|摘要", re.I)
_BACKMATTER = re.compile(r"five[\s-]?year (financial )?summary|五年財務摘要|五年财务摘要", re.I)
# The notes section opens at note 1 ("1. Corporate information" / "1 General information"),
# even when a filing omits the explicit "Notes to…" banner.
_NOTE_ONE = re.compile(r"(?m)^\s*(note\s*)?1[.)、]?\s+[A-Za-z一-鿿]{2,}")


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


def _title_zone(text: str, limit: int = 6) -> list[str]:
    """The page's heading lines: the first few non-empty lines, minus the leading page number
    and the repeating running header. Real report titles sit just beneath the running chrome."""
    out: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if re.fullmatch(r"\d{1,4}", s):                 # a bare page number
            continue
        if _RUNNING_HEADER.search(s):                   # company / "Annual Report YYYY" band
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _title_candidates(lines: list[str]) -> list[str]:
    """Heading-like lines plus joins of consecutive heading-like lines — so a statement title
    split across two lines ('CONSOLIDATED STATEMENT OF' / 'CASH FLOWS') is matched as one."""
    cands = [l for l in lines if _looks_like_heading(l)]
    run: list[str] = []
    for l in lines:
        if _looks_like_heading(l):
            run.append(l)
        elif len(run) >= 2:
            cands.append(" ".join(run)); run = []
        else:
            run = []
    if len(run) >= 2:
        cands.append(" ".join(run))
    return cands


def _title_matches(text: str, patterns: list[str]) -> bool:
    for c in _title_candidates(_title_zone(text)):
        low = c.lower()
        if any(re.search(rx, low) for rx in patterns):
            return True
    return False


def _statement_at_top(text: str) -> str | None:
    """Which face statement the page's heading names, or None when no title is present.

    A continuation page ("CONSOLIDATED STATEMENT OF FINANCIAL POSITION" repeated, or no title
    at all) is handled by the caller, which carries the last-seen statement forward.
    """
    zone = " ".join(_title_zone(text)).lower()
    if _SUMMARY_CTX.search(zone):
        return None
    cands = [c.lower() for c in _title_candidates(_title_zone(text))]
    for statement, patterns in _STATEMENT_TITLES:
        for c in cands:
            if any(re.search(rx, c) for rx in patterns):
                return statement
    return None


def _face_title_at_top(text: str) -> bool:
    """A face-statement title as a heading beneath the running header — excluding the
    highlights / summary pages that quote a statement name without being one."""
    zone = " ".join(_title_zone(text)).lower()
    if _SUMMARY_CTX.search(zone):
        return False
    return _title_matches(text, _FACE_TITLES)


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

        # Annual reports run in order: narrative (cover / MD&A / directors / auditor) → the face
        # statements → the notes → back-matter (five-year summary). We track that region so a
        # note page that quotes a face phrase in prose isn't re-read as a face, and a highlights
        # page that quotes one isn't a false statement. Regions: pre → face → notes → post.
        region = "pre"
        # The statement most recently named by a heading. Real filings run a statement across
        # several pages and only title the first (or repeat the title), so a face page with no
        # resolvable title inherits the previous one.
        current_statement: str | None = None
        for page_src in doc.pages:
            if page_src.index >= len(pdf):
                continue
            text = pdf[page_src.index].get_text("text") or ""

            face_title = _face_title_at_top(text)
            notes_header = _title_matches(text, _NOTES_HEADERS)
            note_one = bool(_NOTE_ONE.search(text)) and not face_title
            backmatter = bool(_BACKMATTER.search(" ".join(_title_zone(text))))

            if region in ("pre", "face") and notes_header:
                region = "notes"
            elif region == "pre" and face_title:
                region = "face"
            elif region == "face" and note_one:        # banner-less notes start at note 1
                region = "notes"
            if region == "notes" and backmatter:        # five-year summary etc. after the notes
                region = "post"

            if region == "face":
                kind, conf = PageKind.FACE, 0.72
                named = _statement_at_top(text)
                if named:
                    current_statement = named
                page_src.statement = current_statement
            elif region == "notes":
                kind, conf = PageKind.NOTES, 0.75 if notes_header else 0.6
                current_statement = None      # the face run has ended
            else:
                kind, conf = PageKind.OTHER, 0.4

            page_src.kind = kind
            page_src.classification_confidence = conf

        pdf.close()
        stmts = {p.statement for p in doc.face_pages() if p.statement}
        ctx.log(f"classify:face={len(doc.face_pages())} notes={len(doc.notes_pages())} "
                f"statements={sorted(stmts)}")
        return doc

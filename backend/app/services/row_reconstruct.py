"""Words → line items, shared by the native-PDF and OCR paths.

Both the native text layer (PyMuPDF words) and the scanned path (OCR words) produce the
same thing: positioned words with a normalized bounding box. This module groups them into
rows, separates label / note-ref / value columns, and emits ``LineItem``s whose
``ExtractedValue.provenance`` carries the page + normalized bbox — so click-to-source works
identically whether the value came from a text layer or from OCR. Values are read here
(deterministically); semantic mapping to canonical concepts happens later.

Two layouts are handled. Most statement faces are *two-column comparatives* (current / prior,
optionally × consolidated / standalone). A statement of changes in equity is a *matrix*: its
columns are equity components (share capital, share premium, each reserve, retained profits,
total, non-controlling interests, total equity) and its rows are movements. Reading a matrix
with the two-column reconstruction produces nonsense — the columns are attributed to periods
that do not exist and the movement date is read as a value — so it gets its own path
(``_detect_matrix`` … ``_matrix_items``) that names every column from the header band.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.models.enums import Basis, LineRole, ValueSource
from app.core.models.geometry import BBox, Provenance
from app.core.models.line_item import ExtractedValue, LineItem, NoteRef, UnitContext
# The section vocabulary is a property of how statements are PRINTED, not of any ontology, so
# reading a banner here uses the same function mapping does rather than a second copy of it.
from app.services.mapping import section_of_banner

_NUM = re.compile(r"^\(?-?[\d,]*\.?\d+\)?%?$")
_NOTE = re.compile(r"^note[s]?\.?$", re.IGNORECASE)
# A column header for the note-reference column (English + Chinese). Real statements print it
# once at the top; the cells beneath it hold bare note numbers, not monetary values.
_NOTE_HDR = re.compile(r"^(notes?|附註|附注)$", re.IGNORECASE)


def _is_note_number(t: str) -> bool:
    """A bare 1–2 digit integer — the shape of a note reference (never a formatted amount).

    A row often cites several notes ("14, 16(b)", "8, 13"), so the token carries the separator
    that followed it; it is still a note reference, not an amount.
    """
    return re.fullmatch(r"\d{1,2}", t.strip().strip(".,;")) is not None


def _is_money_like(t: str, fmt=None) -> bool:
    """A numeric token that is NOT a bare note number (has a separator/decimal/sign, or ≥3 digits
    — i.e. a real amount). Used to confirm a leading small integer is a note ref, not a value."""
    return _num(t, fmt) is not None and not _is_note_number(t)


# A running-header / statement-title / period-caption label. These carry the entity or the
# statement name + a period date, not a financial line — and the only "number" on them is a
# date fragment (a year or a day-of-month).
_RUNNING_HDR = re.compile(r"annual report|interim report|年報|年度報告|中期報告", re.IGNORECASE)
_HDR_LABEL = re.compile(
    r"statement of|year ended|for the (year|period)|as at\b|as of\b|period ended|"
    r"截至|止年度|財務狀況|现金流量|現金流量|權益變動|权益变动|全面收益|損益及其他|损益及其他|"
    r"綜合.{0,8}表|综合.{0,8}表",
    re.IGNORECASE)


def _is_date_ish(d) -> bool:
    """A value that is really a date fragment: a year (1990–2099) or a day-of-month (1–31),
    with no fractional part (so a real figure like 0.45 or 12,345 never qualifies)."""
    try:
        iv = int(d)
    except (TypeError, ValueError):
        return False
    if iv != d:
        return False
    a = abs(iv)
    return 1 <= a <= 31 or 1990 <= a <= 2099


# A period caption written in CJK numerals — "二零二三年" (2023), "二零二二年" (2022) — is how
# HK/PRC filings head their comparative columns. Also the plain Arabic-numeral year.
_PERIOD_TOKEN = re.compile(r"[〇零一二三四五六七八九十]{2,6}年|\b(19|20)\d{2}\b|"
                           r"[〇零一二三四五六七八九十]{1,2}月|[〇零一二三四五六七八九十]{1,3}日")


def _is_period_only_label(label: str) -> bool:
    """True when the label is nothing but period captions (a column-header row).

    "二零二三年 二零二二年" heads the comparative columns; it is not a line item, whatever
    numbers happen to land on its baseline. Requires that removing the period tokens leaves
    no substantive word, so "Profit for the year ended 2023" is never mistaken for a header.
    """
    if not label or not label.strip():
        return False
    rest = _PERIOD_TOKEN.sub(" ", label)
    rest = re.sub(r"[\s\-–—/、,，.。()（）:：'\u2019\"]+", " ", rest).strip()
    return not rest


def _is_heading_with_note_only(label: str, vals: list) -> bool:
    """A section heading whose only "value" is a note reference that drifted into the row.

    Statement sections ("EQUITY HOLDERS OF THE PARENT", "NON-CURRENT ASSETS") carry no amount;
    when the sole number on the line is note-sized, it is the note column, not a figure.
    Restricted to labels with no lower-case letters so a real caption keeps its value.
    """
    if not vals or not label:
        return False
    letters = [c for c in label if c.isalpha() and c.isascii()]
    if not letters or any(c.islower() for c in letters):
        return False
    return all(_is_date_ish(v) for v in vals)


def _is_noise_row(label: str, vals: list) -> bool:
    """A title / running-header / period-caption line that leaked in as a row. Dropped only when
    the label is header-like AND every extracted value is a date fragment — so a genuine line that
    merely mentions a statement name (its value being a real amount) is never removed."""
    if _RUNNING_HDR.search(label):
        return True
    if _is_period_only_label(label):
        return True
    if _is_heading_with_note_only(label, vals):
        return True
    return bool(vals) and bool(_HDR_LABEL.search(label)) and all(_is_date_ish(v) for v in vals)


@dataclass
class Word:
    text: str
    bbox: BBox   # normalized [0,1], page top-left origin


def _num(t: str, fmt=None) -> Decimal | None:
    """Parse a token to a Decimal. With no ``fmt`` this uses the fast US-format path (comma
    thousands, dot decimal) — unchanged behaviour. When a locale ``NumberFormat`` is supplied
    it delegates to ``services.numbers.parse_number`` so EU decimal-comma (``1.234,56``),
    Indian grouping (``1,23,456``) and Arabic-Indic digits parse correctly (Req 12)."""
    if fmt is not None:
        from app.services.numbers import parse_number

        p = parse_number(t, fmt)
        return p.value_raw if p.ok else None
    if not _NUM.match(t.strip()):
        return None
    s = t.strip().replace(",", "").replace("%", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        d = Decimal(s)
        return -d if neg else d
    except InvalidOperation:
        return None


def _group_rows(words: list[Word], y_tol: float = 0.012) -> list[list[Word]]:
    """Cluster words into visual rows by vertical position, then order left→right."""
    ordered = sorted(words, key=lambda w: (w.bbox.y0, w.bbox.x0))
    rows: list[list[Word]] = []
    for w in ordered:
        yc = (w.bbox.y0 + w.bbox.y1) / 2
        placed = False
        for row in rows:
            ryc = sum((x.bbox.y0 + x.bbox.y1) / 2 for x in row) / len(row)
            if abs(yc - ryc) <= y_tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w.bbox.x0)
    rows.sort(key=lambda r: min(w.bbox.y0 for w in r))
    return rows


def _scan_row(row: list[Word], fmt=None) -> tuple[list[Word], str | None, list[Word]]:
    """Split one visual row into (label words, note-ref, value words).

    A "Note"/"Notes" token plus the *single* following number is a note reference, not a
    value — the value lives in the far-right column, so it must not be consumed as a value.
    """
    label_words: list[Word] = []
    note_ref: str | None = None
    value_words: list[Word] = []
    i = 0
    while i < len(row):
        tok = row[i].text.strip()
        if _NOTE.match(tok):
            if i + 1 < len(row) and _num(row[i + 1].text, fmt) is not None:
                note_ref = row[i + 1].text.strip().strip(".")
                i += 2
                continue
        if _num(tok, fmt) is not None:
            value_words.append(row[i])
        elif not value_words:   # text before any number is part of the label
            label_words.append(row[i])
        i += 1
    return label_words, note_ref, value_words


def _row_box(row: list[Word]) -> BBox:
    b = row[0].bbox
    for w in row[1:]:
        b = b.union(w.bbox)
    return b


def _looks_like_header(label_words: list[Word]) -> bool:
    """A section header (e.g. "Non-current assets", "ASSETS") is a standalone label line,
    NOT a wrapped continuation — never fold it into a neighbouring valued row."""
    text = " ".join(w.text for w in label_words).strip()
    if not text:
        return True
    if text.rstrip(":").isupper():          # ALL-CAPS banners
        return True
    if text.endswith(":"):                  # "Represented by:" style headers
        return True
    return False


# Words that cannot END a finished caption ("TOTAL ASSETS LESS CURRENT …") or that can only
# CONTINUE one ("… AND CASH EQUIVALENTS", "… FOR THE YEAR"). Their presence is what separates a
# wrapped ALL-CAPS label from a genuine ALL-CAPS section banner ("ASSETS", "EQUITY").
# Bare adjectives and connectives cannot end a finished caption, so a line ending in one is a
# wrapped head. "TOTAL COMPREHENSIVE" / "LOSS FOR THE YEAR" is the case that matters most: losing
# the head leaves the tail to be mapped as the profit-or-loss bottom line it is not.
_HEAD_INCOMPLETE = re.compile(
    r"\b(less|in|and|or|of|for|to|from|with|net|total|other|that|which|current|non"
    r"|comprehensive|gross|accumulated|retained|attributable)\s*$",
    re.IGNORECASE)
_CONT_STARTS = re.compile(r"^\s*(and|or|of|for|to|in|from|with|that|which|upon)\b",
                          re.IGNORECASE)
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def _CJK_ONLY(text: str) -> bool:  # noqa: N802 - reads as a predicate at call sites
    """Text that carries Han characters and no Latin words — a translation line."""
    return bool(_HAN.search(text)) and not re.search(r"[A-Za-z]{2,}", text)


def _is_wrapped_head(head: list[Word], cont: list[Word]) -> bool:
    """Whether an ALL-CAPS label-only line is the first line of a WRAPPED caption.

    Statement faces print both: banners that head a group ("ASSETS", "NON-CURRENT
    LIABILITIES") and long captions that wrap ("TOTAL ASSETS LESS CURRENT" / "LIABILITIES",
    "NET DECREASE IN CASH" / "AND CASH EQUIVALENTS"). Treating every ALL-CAPS line as a banner
    discards the head and leaves the valued row labelled with a meaningless tail — which then
    maps to whatever concept that tail resembles. Grammar tells them apart: a wrapped head ends
    mid-phrase, or its continuation begins with a connective.
    """
    head_text = " ".join(w.text for w in head).strip()
    cont_text = " ".join(w.text for w in cont).strip()
    if not head_text or not cont_text:
        return False
    # A bilingual filing prints the translation of the SAME caption on the next line. A
    # CJK-only continuation is therefore never a new banner — and without this the Chinese
    # line breaks the chain between an English wrap and the row carrying the figures.
    if _CJK_ONLY(cont_text):
        return True
    # In a bilingual filing the translation is appended to the SAME row, so the head's last
    # English word is not the row's last word. Grammar is judged on the Latin portion only.
    head_latin = re.sub(r"\s+", " ", _HAN.sub(" ", head_text)).strip()
    return bool(_HEAD_INCOMPLETE.search(head_latin)) or bool(_CONT_STARTS.match(cont_text))


def _merge_wrapped_labels(rows: list[list[Word]], fmt=None) -> list[list[Word]]:
    """Fold a label-only line into the following valued row when the two are clearly one
    wrapped label: tight vertical spacing *and* left-alignment inside the label column.

    Conservative on purpose — a wrong merge corrupts a label. A label-only line that reads
    like a section header, or that is loosely spaced / mis-aligned, is left untouched (the
    main loop then simply skips it, as before).
    """
    out: list[list[Word]] = []
    pending: list[Word] = []
    for idx, row in enumerate(rows):
        label_words, note_ref, value_words = _scan_row(row, fmt)
        if value_words:
            out.append(pending + row if pending else row)
            pending = []
            continue
        # Label-only (or note-only) line: candidate wrapped-label continuation.
        nxt = rows[idx + 1] if idx + 1 < len(rows) else None
        is_wrap = (
            nxt is not None
            and label_words
            and note_ref is None
            # An ALL-CAPS banner is not a continuation — unless grammar shows the caption
            # actually wraps into the next line (see `_is_wrapped_head`).
            and (not _looks_like_header(label_words)
                 or _is_wrapped_head(label_words, _scan_row(nxt, fmt)[0]))
            and _scan_row(nxt, fmt)[2]                  # next row actually carries values
            and _wrap_adjacent(_row_box(row), _row_box(nxt), _scan_row(nxt, fmt)[0])
        )
        if is_wrap:
            pending = pending + row
        else:
            out.append(pending + row if pending else row)
            pending = []
    if pending:                                          # trailing label-only text, no value
        out.append(pending)
    return out


def _tight_below(cur: BBox, nxt: BBox) -> bool:
    """True when `nxt` is the next printed line of the same text block as `cur` — the vertical
    half of the wrap test, also used to walk a stacked column-header band line by line."""
    gap = nxt.y0 - cur.y1
    line_h = max(cur.y1 - cur.y0, 1e-4)
    return -0.5 * line_h <= gap <= 0.6 * line_h


def _wrap_adjacent(cur: BBox, nxt: BBox, nxt_label: list[Word]) -> bool:
    """True when `cur` sits directly above `nxt`'s label with paragraph-tight spacing."""
    if not _tight_below(cur, nxt):                       # tight spacing (same text block)
        return False
    label_x0 = min((w.bbox.x0 for w in nxt_label), default=nxt.x0)
    return abs(cur.x0 - label_x0) <= 0.06                # left-aligned in the label column


_CONSOL = re.compile(r"consolidat", re.IGNORECASE)
_STANDALONE = re.compile(r"standalone|separate", re.IGNORECASE)


def _basis_bands(rows: list[list[Word]]) -> list[tuple[Basis, float]]:
    """Detect a two-level Consolidated/Standalone column header and return each basis token's
    horizontal centre, so value columns can be attributed to the right basis. Financial
    statements frequently present both bases side by side; when no such header exists the
    result is empty and everything is treated as consolidated (the common single-basis case)."""
    best: list[tuple[Basis, float]] = []
    for row in rows:
        bands: list[tuple[Basis, float]] = []
        for w in row:
            xc = (w.bbox.x0 + w.bbox.x1) / 2
            if _CONSOL.search(w.text):
                bands.append((Basis.CONSOLIDATED, xc))
            elif _STANDALONE.search(w.text):
                bands.append((Basis.STANDALONE, xc))
        # The header band is the row that mentions both bases (or the most).
        if len({b for b, _ in bands}) >= 2 or len(bands) > len(best):
            best = bands
        if len({b for b, _ in bands}) >= 2:
            break
    return best


def _basis_for(x: float, bands: list[tuple[Basis, float]]) -> Basis:
    if not bands:
        return Basis.CONSOLIDATED
    return min(bands, key=lambda b: abs(b[1] - x))[0]


# Value columns are printed on a tight vertical alignment — every figure in the current-period
# column shares an x-centre to within a fraction of the column gap. This is the width within
# which two figures are taken to be in the same column.
_COL_TOL = 0.035
# A column has to be used by several rows to be a column at all, so a stray figure in a footnote
# or a page number never becomes one.
_COL_MIN_ROWS = 3


def _value_column_bands(value_xs: list[list[tuple[float, str]]]) -> list[float]:
    """The x-centres of the statement's value columns, from the figures on the page.

    A row's period CANNOT be taken from the order of its own values. When a filing reports a line
    in one period only — "Pledged deposits" with a prior-year figure and no current one — the
    single figure sits under the PRIOR column, and reading it as "the first value, therefore
    current" files real money against the wrong year. It is silent: the row looks fine, and only
    the section subtotal reveals it, over-stating one period and under-stating the other by the
    same amount.

    A note-reference column is excluded, because it is not a period. Statements print note refs
    in their own narrow column, and where enough rows carry one it aligns as tightly as any money
    column — so taken as column 0 it makes every real figure on the page one period too late, and
    a whole page of current-year figures is filed against the prior year. What distinguishes it is
    its contents: bare 1–2 digit integers, never formatted amounts.

    Returns [] when the page has no columnar structure to speak of, and the caller falls back to
    positional order.
    """
    flat = sorted((x, t) for xs in value_xs for x, t in xs)
    if not flat:
        return []
    clusters: list[list[tuple[float, str]]] = [[flat[0]]]
    for item in flat[1:]:
        if item[0] - clusters[-1][-1][0] <= _COL_TOL:
            clusters[-1].append(item)
        else:
            clusters.append([item])

    def is_note_column(cluster: list[tuple[float, str]]) -> bool:
        notes = sum(1 for _, t in cluster if _is_note_number(t))
        return notes >= max(2, int(0.8 * len(cluster)))

    kept = [c for c in clusters if len(c) >= _COL_MIN_ROWS and not is_note_column(c)]
    if len(kept) < 2:
        return []                       # nothing to disambiguate; order is as good as position
    return [sorted(x for x, _ in c)[len(c) // 2] for c in kept]   # median resists one outlier


def _column_index(x: float, bands: list[float]) -> int | None:
    """Which value column a figure sits in, or None when it is nowhere near one."""
    if not bands:
        return None
    idx = min(range(len(bands)), key=lambda i: abs(bands[i] - x))
    return idx if abs(bands[idx] - x) <= _COL_TOL * 2 else None


def _detect_note_column(rows: list[list[Word]]) -> float | None:
    """The x-centre of the note-reference column, if the statement has one. Found from a
    'Notes'/'附註' column header that is BACKED by a vertical run of bare note numbers beneath
    it (≥2), so an inline 'Note 14' mention in prose isn't mistaken for a column. Returns None
    when there's no such column (then a per-row heuristic handles a leading note number)."""
    header_xs: list[float] = []
    for row in rows:
        for w in row:
            if _NOTE_HDR.match(w.text.strip()):
                header_xs.append((w.bbox.x0 + w.bbox.x1) / 2)
    best, best_n = None, 0
    for cx in header_xs:
        n = 0
        for row in rows:
            if any(abs((w.bbox.x0 + w.bbox.x1) / 2 - cx) <= 0.03 and _is_note_number(w.text)
                   for w in row):
                n += 1
        if n > best_n:
            best, best_n = cx, n
    return best if best_n >= 2 else None


def _resolve_note_column(note_ref: str | None, value_words: list[Word],
                         note_x: float | None, fmt=None) -> tuple[str | None, list[Word]]:
    """Separate the note-reference cell from the monetary values. When a note column was detected,
    a value token sitting in it (and shaped like a note number) is the reference. Otherwise, a
    leading bare 1–2 digit integer followed by a real amount is treated as the note ref — the
    common ``Revenue  6  45,230  40,110`` layout, where '6' is Note 6, not the current-year value."""
    if note_ref is not None or not value_words:
        return note_ref, value_words
    if note_x is not None:
        kept: list[Word] = []
        for vw in value_words:
            xc = (vw.bbox.x0 + vw.bbox.x1) / 2
            if note_ref is None and abs(xc - note_x) <= 0.03 and _is_note_number(vw.text):
                note_ref = vw.text.strip().strip(".")
            else:
                kept.append(vw)
        return note_ref, kept
    if (len(value_words) >= 2 and _is_note_number(value_words[0].text)
            and any(_is_money_like(w.text, fmt) for w in value_words[1:])):
        return value_words[0].text.strip().strip("."), value_words[1:]
    return note_ref, value_words


_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
           r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
# A single word that can belong to a date-column header phrase.
_DATEISH_WORD = re.compile(
    rf"^(?:{_MONTHS}|\d{{1,4}}(?:st|nd|rd|th)?|\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|"
    r"as|at|year|years?|period|ended|ending|for|the|fy|q[1-4]|h[12]|,)$", re.IGNORECASE)
# A phrase only counts as a period header if it actually carries a year or month name.
_DATE_PHRASE = re.compile(rf"(?:19|20)\d{{2}}|{_MONTHS}", re.IGNORECASE)


def _period_bands(rows: list[list[Word]]) -> list[tuple[str, float]]:
    """Detect date-like column headers (e.g. '31 March 2025' / '2024' / 'FY2025') near the top
    of a statement block and return each period phrase's (label, x-centre). Used to give value
    columns a real period-end DATE for display; empty when no dated header is found (native
    PDFs without a parsable header fall back to positional Current/Prior)."""
    best: list[tuple[str, float]] = []
    for row in rows[:8]:                          # period headers sit at the top of the block
        phrases: list[list[Word]] = []
        run: list[Word] = []
        for w in row:
            dateish = bool(_DATEISH_WORD.match(w.text.strip(" .")))
            # A wide horizontal gap means a new column — flush the current phrase even between
            # two date-ish words (e.g. "…2025    31 March 2024" are two separate headers).
            gap = run and (w.bbox.x0 - run[-1].bbox.x1) > 0.05
            if dateish and not gap:
                run.append(w)
            else:
                if run:
                    phrases.append(run); run = []
                if dateish:
                    run.append(w)
        if run:
            phrases.append(run)
        bands: list[tuple[str, float]] = []
        for ph in phrases:
            text = " ".join(w.text for w in ph).strip(" ,.")
            if _DATE_PHRASE.search(text):         # keep only phrases with a real year/month
                xc = sum((w.bbox.x0 + w.bbox.x1) / 2 for w in ph) / len(ph)
                bands.append((text, xc))
        if len(bands) > len(best):
            best = bands
        if len(bands) >= 2:                        # a two-column header is a confident match
            break
    return best


def _period_for(x: float, bands: list[tuple[str, float]]) -> str | None:
    """The detected period label whose column is nearest this value's x-centre, or None."""
    if not bands:
        return None
    return min(bands, key=lambda b: abs(b[1] - x))[0]


# ── Matrix statements (consolidated statement of changes in equity) ──────────────────────
#
# A matrix face has one value column per equity COMPONENT, captioned by a bilingual header band
# ("Share" / "premium" / "account" / "股份" / "溢價賬" stacked over the column). Detection is
# geometric so a mis-classified page still parses: ≥5 value columns on ≥3 rows is a layout no
# two-column comparative produces (four columns is the maximum there — 2 bases × 2 periods).
_MATRIX_MIN_COLS = 5
_MATRIX_MIN_ROWS = 3
# Value cells are RIGHT-aligned in a printed statement, so a column's right edge is its stable
# anchor (a cell's centre drifts with the width of the number in it).
_COL_TOL = 0.012
# Footnote markers hang off reserve columns ("(3,596,236)*", "–*"). Left in place the token
# simply fails to parse and the column silently loses its value.
_FOOTMARK = re.compile(r"[*†#‡]+$")
_NIL_CELL = re.compile(r"^[-–—−]$")
# Header tokens that caption the units or the note reference for a column, not the component.
_UNITS_TOKEN = re.compile(r"[’'`]0{3}|千元|百萬元|億元|亿元|thousands?|millions?|billions?|"
                          r"lakhs?|crores?", re.IGNORECASE)
_NOTE_TOKEN = re.compile(r"note|附註|附注", re.IGNORECASE)


def _xc(w: Word) -> float:
    return (w.bbox.x0 + w.bbox.x1) / 2


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def _line_tol(words: list[Word]) -> float:
    """Row-clustering tolerance for a matrix, derived from the page's own line height.

    The default tolerance is deliberately generous so a slightly skewed scan still groups; in a
    matrix that generosity merges *adjacent* movement lines, which interleaves two captions and
    shifts every figure onto the wrong row. Half a line height keeps the lines apart.
    """
    hs = [w.bbox.y1 - w.bbox.y0 for w in words]
    return max(0.45 * _median(hs), 0.001)


def _cell_text(t: str) -> str:
    return _FOOTMARK.sub("", t.strip())


def _matrix_cells(row: list[Word], fmt=None) -> list[Word]:
    """The value-shaped tokens of a row. A nil dash counts: it carries no amount but it does
    mark a column position, which is what the column geometry is derived from."""
    out: list[Word] = []
    for w in row:
        t = _cell_text(w.text)
        if _NIL_CELL.match(t) or _num(t, fmt) is not None:
            out.append(w)
    return out


def _strong_cells(cells: list[Word], fmt=None) -> int:
    """How many cells are a real amount or a nil dash — i.e. not a bare 1–2 digit integer.
    A footnote line that prints a figure one digit per glyph ("9 , 3 5 8 , 6 1 1 , 0 0 0",
    as bilingual filings do) lands digits in the value columns; requiring a majority of real
    amounts keeps that line out of the matrix."""
    return sum(1 for w in cells
               if _NIL_CELL.match(_cell_text(w.text))
               or _is_money_like(_cell_text(w.text), fmt))


@dataclass
class _Matrix:
    rows: list[list[Word]]
    bands: list[tuple[float, float]]     # (left, right) x-extent of each component column
    first_data: int                      # row index of the first movement row
    pitch: float                         # median column pitch, the scale for header heuristics


def _pitch(edges: list[float]) -> float:
    return _median([edges[i + 1] - edges[i] for i in range(len(edges) - 1)]) or 1.0


def _detect_matrix(rows: list[list[Word]], fmt=None) -> _Matrix | None:
    """Geometry of a matrix face, or None when the page is not one.

    Columns come from the value rows themselves (clustered right edges) rather than from the
    header, because the header is what we then have to *attribute* to them — deriving both from
    the header would let a missing caption invent a column.
    """
    data_idx: list[int] = []
    cells_by_row: dict[int, list[Word]] = {}
    for i, row in enumerate(rows):
        cells = _matrix_cells(row, fmt)
        if len(cells) >= _MATRIX_MIN_COLS and _strong_cells(cells, fmt) * 2 >= len(cells):
            data_idx.append(i)
            cells_by_row[i] = cells
    if len(data_idx) < _MATRIX_MIN_ROWS:
        return None

    groups: list[list[float]] = []
    for e in sorted(w.bbox.x1 for i in data_idx for w in cells_by_row[i]):
        if groups and e - groups[-1][-1] <= _COL_TOL:
            groups[-1].append(e)
        else:
            groups.append([e])
    # A column of the matrix appears on most rows. A one-off cluster is a date fragment in a
    # label ("At 1 January 2022") or an inline note reference, not a column.
    min_support = max(2, (len(data_idx) + 2) // 3)
    edges = [_median(g) for g in groups if len(g) >= min_support]
    if len(edges) < _MATRIX_MIN_COLS:
        return None
    # Trim clusters standing off on their own — a note column, or label digits that happened to
    # line up — so the value area is the evenly pitched run of component columns.
    while len(edges) > _MATRIX_MIN_COLS and edges[1] - edges[0] > 2.5 * _pitch(edges):
        edges.pop(0)
    while len(edges) > _MATRIX_MIN_COLS and edges[-1] - edges[-2] > 2.5 * _pitch(edges):
        edges.pop()
    pitch = _pitch(edges)
    bands = [(edges[0] - pitch if k == 0 else edges[k - 1], edges[k])
             for k in range(len(edges))]
    return _Matrix(rows=rows, bands=bands, first_data=data_idx[0], pitch=pitch)


def _band_of(w: Word, bands: list[tuple[float, float]]) -> int | None:
    """The component column this word sits in, by x-centre — the same banding idea
    ``_period_bands``/``_basis_bands`` use for periods and bases."""
    xc = _xc(w)
    for k, (left, right) in enumerate(bands):
        if left < xc <= right:
            return k
    return None


def _x_runs(row: list[Word], gap: float) -> list[list[Word]]:
    """Split a header row into horizontally contiguous phrases. A caption sits inside one
    column with clear air on both sides; a *spanner* ("Attributable to owners of the parent")
    is one tight phrase laid across several columns and must not be read as any of their names.
    """
    runs: list[list[Word]] = []
    for w in row:
        if runs and w.bbox.x0 - runs[-1][-1].bbox.x1 <= gap:
            runs[-1].append(w)
        else:
            runs.append([w])
    return runs


def _caption_words(row: list[Word], m: _Matrix) -> dict[int, list[Word]]:
    """The words of one header row that genuinely caption a single column, keyed by column."""
    out: dict[int, list[Word]] = {}
    # Word spacing scales with the column width, so the "clear air" that separates two captions
    # is measured against the pitch rather than a fixed fraction of the page.
    for run in _x_runs(row, max(0.004, 0.15 * m.pitch)):
        spanned = {b for b in (_band_of(w, m.bands) for w in run) if b is not None}
        if len(spanned) >= 2 and len(run) >= 3:      # a group spanner, not a column caption
            continue
        for w in run:
            if w.bbox.x1 - w.bbox.x0 > m.pitch:      # too wide to belong to one column
                continue
            if _UNITS_TOKEN.search(w.text) or _NOTE_TOKEN.search(w.text):
                continue
            k = _band_of(w, m.bands)
            if k is not None:
                out.setdefault(k, []).append(w)
    return out


def _join_caption(parts: list[str]) -> str:
    """Join caption fragments, honouring the hyphen a printed column header wraps on
    ("Non-" / "controlling" / "interests" is one word plus two, not three)."""
    text = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if text and not text.endswith("-"):
            text += " "
        text += p
    return text.strip()


def _matrix_column_names(m: _Matrix) -> list[str] | None:
    """Name every component column from the header band, or None if that cannot be done.

    Returns None rather than a partial answer: a column we cannot name is a column whose figures
    we cannot attribute, and a made-up or duplicated name would silently merge two components.
    """
    per_row = [_caption_words(m.rows[i], m) for i in range(m.first_data)]
    # The header band is anchored by the rows that caption most columns at once (the last line
    # of the English captions, the Chinese line, the units line).
    anchor = [i for i, caps in enumerate(per_row)
              if len(caps) >= max(3, (len(m.bands) + 1) // 2)]
    if not anchor:
        return None
    start, end = min(anchor), max(anchor)
    # A three-line caption ("Share" / "premium" / "account") puts its first line ABOVE the row
    # that names every column, so extend upward through tightly spaced lines that caption
    # something — but no further, or the statement title and the group spanner join the names.
    while (start > 0 and per_row[start - 1]
           and _tight_below(_row_box(m.rows[start - 1]), _row_box(m.rows[start]))):
        start -= 1

    names: list[str] = []
    for k in range(len(m.bands)):
        words = [w for i in range(start, end + 1) for w in per_row[i].get(k, [])]
        latin = [w.text for w in words if re.search(r"[A-Za-z]", w.text)]
        # Prefer the English caption as the key; a Chinese-only filing keeps its own wording.
        name = _join_caption(latin) or _join_caption([w.text for w in words])
        if not name:
            return None
        names.append(name)
    return names if len(set(names)) == len(names) else None


def _heads_indented_block(words: list[Word]) -> bool:
    """A caption that HEADS the indented rows beneath it rather than wrapping into the next
    valued row — "Other comprehensive income/(loss) for the year:" and its CJK twin ending in
    the fullwidth colon. Gluing such a caption onto the first row below it corrupts that label.
    """
    if _looks_like_header(words):
        return True
    return " ".join(w.text for w in words).strip().endswith(("：", "﹕"))


def _matrix_basis(words: list[Word]) -> Basis:
    """One basis for the whole matrix. Its columns are components, so the Consolidated/Standalone
    banding used for comparatives would read them as bases and split the row apart."""
    text = " ".join(w.text for w in words)
    if _STANDALONE.search(text) and not _CONSOL.search(text):
        return Basis.STANDALONE
    return Basis.CONSOLIDATED


def _is_matrix_noise(label: str, row_text: str, vals: list) -> bool:
    """A running header / page footer / statement title whose stray year landed in a value column.

    Deliberately laxer than ``_is_noise_row`` in one respect: a period-only label is *not* noise
    here, because "At 1 January 2023" / "於二零二三年一月一日" IS the opening-balance movement
    row. Chrome is recognised instead from the whole printed line — the page footer's company
    name sits in the label column while its "Annual Report 2023" sits over the value columns.
    """
    if _RUNNING_HDR.search(row_text):
        return True
    if not vals or not all(_is_date_ish(v) for v in vals):
        return False
    return bool(_HDR_LABEL.search(label)) or _is_period_only_label(label)


def _matrix_items(m: _Matrix, names: list[str], *, page_index: int, document_id: str | None,
                  source_kind: str, ordinal_start: int,
                  fmt=None) -> tuple[list[LineItem], int]:
    """One LineItem per MOVEMENT ROW, its values keyed by component-column name.

    Why one item per row rather than one per cell: ``LineItem.values`` is already a dict keyed by
    ``ValueKey(basis, period_end, period_label)``, so a single row holds as many named values as
    it has columns, and ``_serialize_rows`` ships ``period_label`` + ``period_display`` per value
    — the API and the statement view therefore render named component columns with no change
    downstream (``excel_extract`` already puts real column-header text in ``period_label``).
    One item per cell would multiply a 14-column statement into ~200 rows, destroy the row
    ordering the statement view relies on, and flood mapping with duplicate labels.

    The positional "current"/"prior" keys are deliberately NOT used: a component is not a period,
    and labelling it so would feed equity components into period-over-period arithmetic.
    """
    items: list[LineItem] = []
    ordinal = ordinal_start
    basis = _matrix_basis([w for row in m.rows for w in row])
    value_left = m.bands[0][0]
    pending: list[Word] = []                 # label lines waiting for the row that has figures
    tail: BBox | None = None                 # box of the LAST pending line, for the wrap test
    for i in range(m.first_data, len(m.rows)):
        row = m.rows[i]
        label_words = [w for w in row if _xc(w) <= value_left]
        cells = [w for w in _matrix_cells(row, fmt) if _band_of(w, m.bands) is not None]

        # A movement in equity always touches at least its component and a total column, so a
        # lone figure on a line is chrome (a page footer's year), not a row of the matrix.
        if len(cells) < 2 or _strong_cells(cells, fmt) * 2 < len(cells):
            # No amounts on this line. Either the first line of a wrapped movement caption, or
            # a footnote whose glyph-split digits fell in the columns (cells but no amounts).
            if cells or not label_words:
                pending, tail = [], None
                continue
            box = _row_box(label_words)
            # Only vertical adjacency is required: the label column of a matrix holds nothing
            # else, and a bilingual continuation line is indented to sit under the *Chinese*
            # caption ("十二月三十一日" beneath "於二零二三年"), so the left-edge test
            # ``_wrap_adjacent`` applies to a two-column face would reject a genuine wrap.
            if tail is not None and not _tight_below(tail, box):
                pending = []                       # not a continuation, a new block
            pending, tail = pending + label_words, box
            if _heads_indented_block(pending):
                pending, tail = [], None
            continue

        if tail is not None and not _tight_below(tail, _row_box(label_words or row)):
            pending = []
        label_words, pending, tail = pending + label_words, [], None
        label = " ".join(w.text for w in label_words).strip()
        if not label:
            continue
        vals = [d for d in (_num(_cell_text(w.text), fmt) for w in cells) if d is not None]
        if _is_matrix_noise(label, " ".join(w.text for w in row), vals):
            continue

        li = LineItem(source_label=label, ordinal=ordinal, role=LineRole.LINE,
                      source=ValueSource.MACHINE)
        label_bbox = _union([w.bbox for w in label_words])
        for cw in cells:
            # A nil dash is printed for "no movement"; it is not a figure, so no value is
            # emitted for it — the same reason the two-column path never invents a zero.
            dec = _num(_cell_text(cw.text), fmt)
            if dec is None:
                continue
            k = _band_of(cw, m.bands)
            prov = Provenance(
                document_id=document_id, page_index=page_index, bbox=cw.bbox,
                value_bbox=cw.bbox, label_bbox=label_bbox, text_snippet=label,
                source_kind=source_kind, producer=f"extract:{source_kind}@0.1.0",
            )
            li.set_value(ExtractedValue(
                value_raw=dec, value=dec, basis=basis,
                # The component name is both the key and the column header shown in the UI.
                period_label=names[k], period_display=names[k],
                unit_ctx=UnitContext(), provenance=prov,
            ))
        if li.values:
            items.append(li)
            ordinal += 1
    return items, ordinal


def _maybe_matrix(words: list[Word], *, statement: str | None,
                  fmt=None) -> tuple[_Matrix | None, list[str] | None]:
    """Matrix geometry + column names for a matrix page, else (None, None).

    Skips the (re-)grouping entirely for pages that cannot be a matrix, so the two-column
    reconstruction of every other statement face costs exactly what it did before.
    """
    if statement != "changes_in_equity":
        numeric = sum(1 for w in words if _num(_cell_text(w.text), fmt) is not None
                      or _NIL_CELL.match(_cell_text(w.text)))
        if numeric < _MATRIX_MIN_COLS * _MATRIX_MIN_ROWS:
            return None, None
    m = _detect_matrix(_group_rows(words, _line_tol(words)), fmt)
    if m is None:
        return None, None
    return m, _matrix_column_names(m)


def build_line_items(words: list[Word], *, page_index: int, document_id: str | None,
                     source_kind: str, ordinal_start: int = 0,
                     number_format=None, statement: str | None = None,
                     log=None) -> tuple[list[LineItem], int]:
    """Reconstruct line items from positioned words. Returns (items, next_ordinal).

    Consolidated and standalone columns are extracted in one pass: a Consolidated/Standalone
    header band (if present) attributes each value column to its basis; within a basis,
    left→right columns become current / prior periods. ``number_format`` (a locale
    ``NumberFormat``) makes value parsing locale-correct; omit for the US default.

    ``statement`` is the page classifier's verdict; ``"changes_in_equity"`` selects the matrix
    path, which a matrix layout also selects on its own so a mis-classified page still parses.
    ``log`` (``ctx.log``) records why a matrix page was skipped or fell back."""
    matrix, names = _maybe_matrix(words, statement=statement, fmt=number_format)
    if matrix is not None and names is not None:
        if log:
            log(f"extract:page={page_index}:equity_matrix_columns={len(names)}")
        return _matrix_items(matrix, names, page_index=page_index, document_id=document_id,
                             source_kind=source_kind, ordinal_start=ordinal_start,
                             fmt=number_format)
    if statement == "changes_in_equity":
        # A named matrix we cannot attribute is worse than nothing: every figure would be filed
        # under a period that does not exist. Report it and emit no rows for the page. A page
        # with no matrix layout at all is a genuinely two-column equity statement (small
        # entities present one), so that one falls through to the normal reconstruction.
        if matrix is not None:
            if log:
                log(f"extract:page={page_index}:equity_matrix_unnamed_columns"
                    f"={len(matrix.bands)}(skipped)")
            return [], ordinal_start
        if log:
            log(f"extract:page={page_index}:equity_no_matrix_layout(two_column_path)")

    items: list[LineItem] = []
    ordinal = ordinal_start
    rows = _merge_wrapped_labels(_group_rows(words), number_format)
    bands = _basis_bands(rows)
    period_bands = _period_bands(rows)          # real period-end dates for column headers, if any
    note_x = _detect_note_column(rows)          # x of the note-ref column, so it isn't read as a value
    # Where the value columns actually are. A first pass over the page's figures (after the note
    # column is removed, so note references never look like a column) so a row reporting only one
    # of two periods still files that figure under the period it is printed in.
    col_xs: list[list[tuple[float, str]]] = []
    for row in rows:
        _lw, _nr, _vw = _scan_row(row, number_format)
        _nr, _vw = _resolve_note_column(_nr, _vw, note_x, number_format)
        xs = [((w.bbox.x0 + w.bbox.x1) / 2, w.text) for w in _vw
              if _num(w.text, number_format) is not None]
        if xs:
            col_xs.append(xs)
    value_bands = _value_column_bands(col_xs)
    section: str | None = None
    for row in rows:
        label_words, note_ref, value_words = _scan_row(row, number_format)
        note_ref, value_words = _resolve_note_column(note_ref, value_words, note_x, number_format)

        label = " ".join(w.text for w in label_words).strip()
        if not label or not value_words:
            # A label-only banner ("NON-CURRENT LIABILITIES", 流動負債) carries no amount, but it
            # scopes every row beneath it — the same caption under two banners is two different
            # concepts. Remember it before dropping the row.
            #
            # A sub-heading ending in a colon usually introduces a group WITHIN the section
            # rather than a new one, so by default it must not displace it: the rows under
            # "Adjustments for:" are still operating-activities rows, and losing that scope is
            # what lets an operating add-back resolve to an investing concept.
            #
            # Unless the sub-heading names a section in its own right. The income statement
            # splits both profit and total comprehensive income with "Attributable to:" /
            # "Total comprehensive income attributable to:", printing the same two captions
            # under each — so that colon heading is the only thing distinguishing them.
            if label and not value_words and _looks_like_header(label_words):
                names_a_section = section_of_banner(label) is not None
                if names_a_section or not label.rstrip().endswith(":"):
                    section = label
            continue

        # Drop running-header / statement-title / period-caption lines that leaked in as rows
        # (their only "value" is a date fragment) — never a genuine financial line.
        row_vals = [d for d in (_num(w.text, number_format) for w in value_words) if d is not None]
        if _is_noise_row(label, row_vals):
            continue

        # A heading is often printed on the SAME line as its first figure, so it never appears as
        # a label-only row: "Total comprehensive loss attributable to: … Owners of the parent"
        # is one row carrying the owners' amount. The heading still scopes this row and the rows
        # under it — without that, the second "Non-controlling interests" of the income statement
        # stays under the profit split and is added to the first, which is meaningless.
        head = re.split(r"[:：]", label)[0] if re.search(r"[:：]", label) else ""
        if head and section_of_banner(head) is not None:
            section = head.strip()

        li = LineItem(source_label=label, ordinal=ordinal, role=LineRole.LINE,
                      section_hint=section, source=ValueSource.MACHINE)
        label_bbox = _union([w.bbox for w in label_words])
        # Group value columns by basis (via the header band), then place each value in its own
        # column within that basis — by position when the page has columns, else by order.
        per_basis: dict[Basis, int] = {}
        basis_cols: dict[Basis, list[int]] = {}
        if value_bands:
            for i, bx in enumerate(value_bands):
                basis_cols.setdefault(_basis_for(bx, bands), []).append(i)
        # Once the page's value columns are known, a figure that sits under NONE of them is not
        # a figure: it is a note reference the note-column heuristics did not catch, printed in
        # its own narrow column to the left. Taken as a value it claims the current period and
        # displaces the row's real figures. Only dropped when the row has at least one figure
        # that IS under a column, so a row the bands do not describe still reports positionally.
        in_col = {id(w): _column_index((w.bbox.x0 + w.bbox.x1) / 2, value_bands)
                  for w in value_words}
        drop_outliers = bool(value_bands) and any(v is not None for v in in_col.values())
        for vw in sorted(value_words, key=lambda w: w.bbox.x0):
            dec = _num(vw.text, number_format)
            if dec is None:
                continue
            if drop_outliers and in_col[id(vw)] is None:
                continue
            xc = (vw.bbox.x0 + vw.bbox.x1) / 2
            basis = _basis_for(xc, bands)
            # The column this figure is printed in decides its period. Order is the fallback for
            # a page with no columnar structure, and for a figure that sits under no column.
            k = per_basis.get(basis, 0)
            col = _column_index(xc, value_bands)
            if col is not None and col in basis_cols.get(basis, []):
                k = basis_cols[basis].index(col)
            per_basis[basis] = max(per_basis.get(basis, 0), k) + 1
            prov = Provenance(
                document_id=document_id, page_index=page_index, bbox=vw.bbox,
                value_bbox=vw.bbox, label_bbox=label_bbox, text_snippet=label,
                source_kind=source_kind, producer=f"extract:{source_kind}@0.1.0",
            )
            li.set_value(ExtractedValue(
                value_raw=dec, value=dec, basis=basis,
                period_label="current" if k == 0 else "prior" if k == 1 else f"col{k}",
                period_display=_period_for(xc, period_bands),  # display-only date, if detected
                unit_ctx=UnitContext(), provenance=prov,
            ))
        if note_ref:
            li.note_refs.append(NoteRef(raw=note_ref, numbers=[note_ref]))
            li.note_number = note_ref
        items.append(li)
        ordinal += 1
    return items, ordinal


def _union(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    b = boxes[0]
    for o in boxes[1:]:
        b = b.union(o)
    return b

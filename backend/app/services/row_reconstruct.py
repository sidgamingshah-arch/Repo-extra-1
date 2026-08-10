"""Words → line items, shared by the native-PDF and OCR paths.

Both the native text layer (PyMuPDF words) and the scanned path (OCR words) produce the
same thing: positioned words with a normalized bounding box. This module groups them into
rows, separates label / note-ref / value columns, and emits ``LineItem``s whose
``ExtractedValue.provenance`` carries the page + normalized bbox — so click-to-source works
identically whether the value came from a text layer or from OCR. Values are read here
(deterministically); semantic mapping to canonical concepts happens later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.models.enums import Basis, LineRole, ValueSource
from app.core.models.geometry import BBox, Provenance
from app.core.models.line_item import ExtractedValue, LineItem, NoteRef, UnitContext

_NUM = re.compile(r"^\(?-?[\d,]*\.?\d+\)?%?$")
_NOTE = re.compile(r"^note[s]?\.?$", re.IGNORECASE)
# A column header for the note-reference column (English + Chinese). Real statements print it
# once at the top; the cells beneath it hold bare note numbers, not monetary values.
_NOTE_HDR = re.compile(r"^(notes?|附註|附注)$", re.IGNORECASE)


def _is_note_number(t: str) -> bool:
    """A bare 1–2 digit integer — the shape of a note reference (never a formatted amount)."""
    return re.fullmatch(r"\d{1,2}", t.strip().strip(".")) is not None


def _is_money_like(t: str, fmt=None) -> bool:
    """A numeric token that is NOT a bare note number (has a separator/decimal/sign, or ≥3 digits
    — i.e. a real amount). Used to confirm a leading small integer is a note ref, not a value."""
    return _num(t, fmt) is not None and not _is_note_number(t)


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
            and not _looks_like_header(label_words)
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


def _wrap_adjacent(cur: BBox, nxt: BBox, nxt_label: list[Word]) -> bool:
    """True when `cur` sits directly above `nxt`'s label with paragraph-tight spacing."""
    gap = nxt.y0 - cur.y1
    line_h = max(cur.y1 - cur.y0, 1e-4)
    if gap > 0.6 * line_h or gap < -0.5 * line_h:        # tight spacing (same text block)
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


def build_line_items(words: list[Word], *, page_index: int, document_id: str | None,
                     source_kind: str, ordinal_start: int = 0,
                     number_format=None) -> tuple[list[LineItem], int]:
    """Reconstruct line items from positioned words. Returns (items, next_ordinal).

    Consolidated and standalone columns are extracted in one pass: a Consolidated/Standalone
    header band (if present) attributes each value column to its basis; within a basis,
    left→right columns become current / prior periods. ``number_format`` (a locale
    ``NumberFormat``) makes value parsing locale-correct; omit for the US default."""
    items: list[LineItem] = []
    ordinal = ordinal_start
    rows = _merge_wrapped_labels(_group_rows(words), number_format)
    bands = _basis_bands(rows)
    period_bands = _period_bands(rows)          # real period-end dates for column headers, if any
    note_x = _detect_note_column(rows)          # x of the note-ref column, so it isn't read as a value
    for row in rows:
        label_words, note_ref, value_words = _scan_row(row, number_format)
        note_ref, value_words = _resolve_note_column(note_ref, value_words, note_x, number_format)

        label = " ".join(w.text for w in label_words).strip()
        if not label or not value_words:
            continue

        li = LineItem(source_label=label, ordinal=ordinal, role=LineRole.LINE,
                      source=ValueSource.MACHINE)
        label_bbox = _union([w.bbox for w in label_words])
        # Group value columns by basis (via the header band), then order within each basis.
        per_basis: dict[Basis, int] = {}
        for vw in sorted(value_words, key=lambda w: w.bbox.x0):
            dec = _num(vw.text, number_format)
            if dec is None:
                continue
            basis = _basis_for((vw.bbox.x0 + vw.bbox.x1) / 2, bands)
            k = per_basis.get(basis, 0)
            per_basis[basis] = k + 1
            prov = Provenance(
                document_id=document_id, page_index=page_index, bbox=vw.bbox,
                value_bbox=vw.bbox, label_bbox=label_bbox, text_snippet=label,
                source_kind=source_kind, producer=f"extract:{source_kind}@0.1.0",
            )
            xc = (vw.bbox.x0 + vw.bbox.x1) / 2
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

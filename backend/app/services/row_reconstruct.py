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


@dataclass
class Word:
    text: str
    bbox: BBox   # normalized [0,1], page top-left origin


def _num(t: str) -> Decimal | None:
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


def _scan_row(row: list[Word]) -> tuple[list[Word], str | None, list[Word]]:
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
            if i + 1 < len(row) and _num(row[i + 1].text) is not None:
                note_ref = row[i + 1].text.strip().strip(".")
                i += 2
                continue
        if _num(tok) is not None:
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


def _merge_wrapped_labels(rows: list[list[Word]]) -> list[list[Word]]:
    """Fold a label-only line into the following valued row when the two are clearly one
    wrapped label: tight vertical spacing *and* left-alignment inside the label column.

    Conservative on purpose — a wrong merge corrupts a label. A label-only line that reads
    like a section header, or that is loosely spaced / mis-aligned, is left untouched (the
    main loop then simply skips it, as before).
    """
    out: list[list[Word]] = []
    pending: list[Word] = []
    for idx, row in enumerate(rows):
        label_words, note_ref, value_words = _scan_row(row)
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
            and _scan_row(nxt)[2]                       # next row actually carries values
            and _wrap_adjacent(_row_box(row), _row_box(nxt), _scan_row(nxt)[0])
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


def build_line_items(words: list[Word], *, page_index: int, document_id: str | None,
                     source_kind: str, ordinal_start: int = 0) -> tuple[list[LineItem], int]:
    """Reconstruct line items from positioned words. Returns (items, next_ordinal)."""
    items: list[LineItem] = []
    ordinal = ordinal_start
    for row in _merge_wrapped_labels(_group_rows(words)):
        label_words, note_ref, value_words = _scan_row(row)

        label = " ".join(w.text for w in label_words).strip()
        if not label or not value_words:
            continue

        li = LineItem(source_label=label, ordinal=ordinal, role=LineRole.LINE,
                      source=ValueSource.MACHINE)
        label_bbox = _union([w.bbox for w in label_words])
        # Value columns left→right → current, prior, …
        for k, vw in enumerate(sorted(value_words, key=lambda w: w.bbox.x0)):
            dec = _num(vw.text)
            if dec is None:
                continue
            prov = Provenance(
                document_id=document_id, page_index=page_index, bbox=vw.bbox,
                value_bbox=vw.bbox, label_bbox=label_bbox, text_snippet=label,
                source_kind=source_kind, producer=f"extract:{source_kind}@0.1.0",
            )
            li.set_value(ExtractedValue(
                value_raw=dec, value=dec, basis=Basis.CONSOLIDATED,
                period_label="current" if k == 0 else "prior" if k == 1 else f"col{k}",
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

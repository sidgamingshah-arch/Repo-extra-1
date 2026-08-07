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


def build_line_items(words: list[Word], *, page_index: int, document_id: str | None,
                     source_kind: str, ordinal_start: int = 0) -> tuple[list[LineItem], int]:
    """Reconstruct line items from positioned words. Returns (items, next_ordinal)."""
    items: list[LineItem] = []
    ordinal = ordinal_start
    for row in _group_rows(words):
        label_words: list[Word] = []
        note_ref: str | None = None
        value_words: list[Word] = []
        i = 0
        while i < len(row):
            tok = row[i].text.strip()
            if _NOTE.match(tok):
                # "Note"/"Notes" + the SINGLE following number is a note reference (not a
                # value — the value lives in the far-right column, so don't consume it).
                if i + 1 < len(row) and _num(row[i + 1].text) is not None:
                    note_ref = row[i + 1].text.strip().strip(".")
                    i += 2
                    continue
            if _num(tok) is not None:
                value_words.append(row[i])
            elif not value_words:   # text before any number is part of the label
                label_words.append(row[i])
            i += 1

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

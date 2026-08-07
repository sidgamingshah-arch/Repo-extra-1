"""Deterministic Excel → line items with exact cell-level provenance.

Native spreadsheets need no OCR and no LLM to extract: the value and its origin are read
straight from the workbook. Each numeric row becomes a ``LineItem`` whose ``ExtractedValue``
carries a ``Provenance`` pointing at the exact sheet + cell (e.g. "P&L!C14"). Column headers
are used to key values by period. Semantic mapping (which canonical concept each row is) is
a separate, LLM-driven step — this stage only produces trustworthy, source-anchored facts.
"""
from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation

from app.core.models.enums import Basis, LineRole, ValueSource
from app.core.models.geometry import Provenance
from app.core.models.line_item import ExtractedValue, LineItem, UnitContext

_PRODUCER = "extract:xlsx@0.1.0"


def _col_letter(idx1: int) -> str:
    """1-based column index → Excel column letters (1→A, 27→AA)."""
    s = ""
    while idx1 > 0:
        idx1, r = divmod(idx1 - 1, 26)
        s = chr(65 + r) + s
    return s


def _to_decimal(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None
    if isinstance(v, str):
        t = v.strip().replace(",", "")
        neg = t.startswith("(") and t.endswith(")")
        t = t.strip("()").replace("%", "").strip()
        if not t:
            return None
        try:
            d = Decimal(t)
            return -d if neg else d
        except InvalidOperation:
            return None
    return None


def extract_workbook(data: bytes, *, document_id: str | None = None) -> list[LineItem]:
    """Read every sheet; emit a LineItem per labelled, numeric row with cell provenance."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    items: list[LineItem] = []
    ordinal = 0
    try:
        for sheet_index, name in enumerate(wb.sheetnames):
            ws = wb[name]
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                continue
            label_col, value_cols = _detect_columns(rows)
            if label_col is None or not value_cols:
                continue
            headers = _period_headers(rows, value_cols)
            for r_idx, row in enumerate(rows):
                if label_col >= len(row):
                    continue
                label = row[label_col]
                if not isinstance(label, str) or not label.strip():
                    continue
                li = _row_item(name, sheet_index, r_idx, label.strip(), row, label_col,
                               value_cols, headers, document_id, ordinal)
                if li is not None:
                    items.append(li)
                    ordinal += 1
    finally:
        wb.close()
    return items


def _detect_columns(rows: list[list]) -> tuple[int | None, list[int]]:
    """Label column = the text-heaviest column; value columns = the numeric ones."""
    width = max((len(r) for r in rows), default=0)
    text_score = [0] * width
    num_score = [0] * width
    for row in rows:
        for c in range(len(row)):
            v = row[c]
            if isinstance(v, str) and v.strip() and _to_decimal(v) is None:
                text_score[c] += 1
            elif _to_decimal(v) is not None:
                num_score[c] += 1
    if not any(num_score):
        return None, []
    label_col = max(range(width), key=lambda c: text_score[c]) if any(text_score) else 0
    value_cols = [c for c in range(width) if c != label_col and num_score[c] >= 1]
    return label_col, value_cols


def _period_headers(rows: list[list], value_cols: list[int]) -> dict[int, str]:
    """Best-effort period label per value column, taken from the first text header row."""
    for row in rows:
        if any(c < len(row) and isinstance(row[c], str) and row[c].strip() for c in value_cols):
            has_numbers = any(_to_decimal(row[c]) is not None for c in value_cols)
            if not has_numbers:
                return {c: (str(row[c]).strip() if c < len(row) and row[c] else f"col{c}")
                        for c in value_cols}
    # Fall back to positional labels (first value column = current period).
    return {c: ("current" if i == 0 else "prior" if i == 1 else f"col{c}")
            for i, c in enumerate(value_cols)}


def _row_item(sheet, sheet_index, r_idx, label, row, label_col, value_cols, headers,
              document_id, ordinal) -> LineItem | None:
    li = LineItem(source_label=label, ordinal=ordinal, role=LineRole.LINE,
                  source=ValueSource.MACHINE)
    got = False
    for c in value_cols:
        if c >= len(row):
            continue
        dec = _to_decimal(row[c])
        if dec is None:
            continue
        prov = Provenance(
            document_id=document_id, page_index=sheet_index, sheet=sheet,
            cell=f"{_col_letter(c + 1)}{r_idx + 1}",
            label_cell=f"{_col_letter(label_col + 1)}{r_idx + 1}",
            text_snippet=label, source_kind="spreadsheet", producer=_PRODUCER,
        )
        ev = ExtractedValue(value_raw=dec, value=dec, basis=Basis.CONSOLIDATED,
                            period_label=headers.get(c, f"col{c}"),
                            unit_ctx=UnitContext(), provenance=prov)
        li.set_value(ev)
        got = True
    return li if got else None

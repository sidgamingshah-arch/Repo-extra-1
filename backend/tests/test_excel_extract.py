"""Deterministic Excel extraction → line items with exact cell-level provenance."""
from __future__ import annotations

import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.core.models.enums import Basis
from app.services.excel_extract import extract_workbook


def _wb_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws.append(["Particulars", "FY2025", "FY2024"])
    ws.append(["Revenue from operations", 964700, 901300])
    ws.append(["Other income", 3619, 2701])
    ws.append(["Total income", 968319, 904001])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_excel_values_and_cell_provenance():
    items = extract_workbook(_wb_bytes(), document_id="doc1")
    labels = {li.source_label for li in items}
    assert {"Revenue from operations", "Other income", "Total income"} <= labels
    assert "Particulars" not in labels  # header row is not a data row

    rev = next(li for li in items if li.source_label == "Revenue from operations")
    cur = rev.get_value(Basis.CONSOLIDATED, period_label="FY2025")
    assert cur is not None and int(cur.value) == 964700
    # Exact, verifiable provenance — sheet + cell — with no OCR/LLM involved.
    assert cur.provenance is not None
    assert cur.provenance.sheet == "P&L"
    assert cur.provenance.cell == "B2"          # row 2, first value column
    assert cur.provenance.label_cell == "A2"
    assert cur.provenance.source_kind == "spreadsheet"
    prior = rev.get_value(Basis.CONSOLIDATED, period_label="FY2024")
    assert prior is not None and cur.provenance.cell != prior.provenance.cell


def test_excel_flows_through_the_pipeline():
    from app.services.documents import run_extraction

    doc, ctx = run_extraction(_wb_bytes(), filename="statements.xlsx")
    assert doc.fmt.value in ("xlsx", "xls")
    assert len(doc.line_items) >= 3
    assert any(ev.provenance and ev.provenance.cell
               for li in doc.line_items for ev in li.values.values())

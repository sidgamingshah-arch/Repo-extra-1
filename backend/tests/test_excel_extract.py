"""Deterministic Excel extraction → line items with exact cell-level provenance."""
from __future__ import annotations

import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.core.models.enums import Basis
from app.services.excel_extract import cell_context, extract_workbook


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


def test_cell_context_windows_around_the_target():
    ctx = cell_context(_wb_bytes(), sheet="P&L", cell="B2", radius=2)
    assert ctx["sheet"] == "P&L" and ctx["target"] == "B2"
    # exactly one target cell, and it holds the right value
    target = [c for line in ctx["grid"] for c in line if c["is_target"]]
    assert len(target) == 1
    assert target[0]["ref"] == "B2" and target[0]["value"] == "964700" and target[0]["numeric"]
    # the label to the left is in the window and readable
    assert any(c["value"] == "Revenue from operations" for line in ctx["grid"] for c in line)
    assert "A" in ctx["col_letters"] and "B" in ctx["col_letters"]


def test_cell_context_rejects_bad_ref_and_unknown_sheet():
    with pytest.raises(ValueError):
        cell_context(_wb_bytes(), sheet="P&L", cell="not-a-cell")
    with pytest.raises(KeyError):
        cell_context(_wb_bytes(), sheet="Nope", cell="B2")


def test_cell_context_endpoint(client):
    import io as _io

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BS"
    ws.append(["Item", "2025"])
    ws.append(["Cash and cash equivalents", 1204])
    buf = _io.BytesIO()
    wb.save(buf)

    doc_id = client.post(
        "/api/v1/documents",
        files={"file": ("bs.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()["id"]

    r = client.get(f"/api/v1/documents/{doc_id}/cell-context", params={"sheet": "BS", "cell": "B2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target"] == "B2"
    assert any(c["is_target"] and c["value"] == "1204" for line in body["grid"] for c in line)

    # PDF documents have no cell context.
    from tests.fixtures.generate import make_native_pdf
    pdf_id = client.post(
        "/api/v1/documents", files={"file": ("x.pdf", make_native_pdf(), "application/pdf")}
    ).json()["id"]
    assert client.get(f"/api/v1/documents/{pdf_id}/cell-context",
                      params={"sheet": "S", "cell": "A1"}).status_code == 400


def test_excel_flows_through_the_pipeline():
    from app.services.documents import run_extraction

    doc, ctx = run_extraction(_wb_bytes(), filename="statements.xlsx")
    assert doc.fmt.value in ("xlsx", "xls")
    assert len(doc.line_items) >= 3
    assert any(ev.provenance and ev.provenance.cell
               for li in doc.line_items for ev in li.values.values())

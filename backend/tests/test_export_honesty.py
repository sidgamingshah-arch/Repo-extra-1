"""Export honesty (Req 8, 10): JSON carries a derived-analysis block and edited formulas,
the flat sheet has a Formula column, edited items carry a formula note in the statement
workbook, and the Include set gates the analysis sheets."""
from __future__ import annotations

import io
import time

import pytest

pytest.importorskip("fitz")

from tests.fixtures.generate import make_native_pdf, make_rich_pdf


def _await(client, doc_id):
    for _ in range(100):
        r = client.get(f"/api/v1/documents/{doc_id}/run")
        if r.status_code == 200 and r.json().get("status") == "succeeded":
            return
        time.sleep(0.05)
    raise AssertionError("did not finish")


def _extract(client, data=None, filename="bs.pdf"):
    doc_id = client.post("/api/v1/documents",
                         files={"file": (filename, data or make_native_pdf(), "application/pdf")}).json()["id"]
    onts = client.get("/api/v1/ontologies").json()
    ont = next((o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v1"), onts[0])
    tpls = client.get("/api/v1/templates").json()
    tpl = next((t for t in tpls if t["template_key"] == ont["target_template_key"]), tpls[0])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    _await(client, doc_id)
    return doc_id


def test_json_export_carries_analysis_and_formula(client):
    doc_id = _extract(client, data=make_rich_pdf(), filename="rich.pdf")
    # Edit a line to attach a formula.
    rows = client.get(f"/api/v1/documents/{doc_id}/run").json()["result"]["rows"]
    key = next(r["canonical_key"] for r in rows if r.get("canonical_key"))
    client.patch(f"/api/v1/documents/{doc_id}/line-items/{key}", json={"value": 123, "formula": "=A1+A2"})

    body = client.get(f"/api/v1/documents/{doc_id}/export", params={"fmt": "json"}).json()
    assert "analysis" in body and body["analysis"]["ratios"]
    assert any(d["key"] == "contingent_liabilities" for d in body["analysis"]["disclosures"])
    edited = next(li for li in body["line_items"] if li["canonical_key"] == key)
    assert edited["edited"] and edited["formula"] == "=A1+A2"


def test_flat_export_has_formula_column(client):
    import openpyxl

    doc_id = _extract(client)
    rows = client.get(f"/api/v1/documents/{doc_id}/run").json()["result"]["rows"]
    key = next(r["canonical_key"] for r in rows if r.get("canonical_key"))
    client.patch(f"/api/v1/documents/{doc_id}/line-items/{key}", json={"value": 5, "formula": "=SUM(x)"})

    x = client.get(f"/api/v1/documents/{doc_id}/export", params={"fmt": "excel", "layout": "flat"})
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    ws = wb["Extraction"]
    header = [c.value for c in ws[1]]
    assert "Formula" in header
    text = " | ".join(str(v) for row in ws.iter_rows(values_only=True) for v in row if v)
    assert "=SUM(x)" in text
    # …and it is TEXT, not a live formula cell. openpyxl promotes a leading "=" to a real formula,
    # and this expression's references are canonical line-item keys, not cell addresses, so the
    # workbook opened with #NAME? where an audit trail was intended.
    cell = next(c for row in ws.iter_rows() for c in row if c.value == "=SUM(x)")
    assert cell.data_type == "s"


def test_workbook_carries_formulas_as_notes_not_live_cells(client):
    """The Excel export does not build a live spreadsheet, and the docs now say so.

    A formula travels for AUDIT: as text in the flat sheet's Formula column, and as a cell NOTE on
    the row's label cell in the statement workbook. References are canonical line-item keys
    resolved server-side by services/formula.py and are never translated to cell addresses, so
    nothing in the file recalculates — the number in the cell is the value the server computed.
    """
    import openpyxl

    doc_id = _extract(client)
    rows = client.get(f"/api/v1/documents/{doc_id}/run").json()["result"]["rows"]
    key = next(r["canonical_key"] for r in rows if r.get("canonical_key"))
    client.patch(f"/api/v1/documents/{doc_id}/line-items/{key}",
                 json={"value": 5, "formula": "=SUM(x)"})

    x = client.get(f"/api/v1/documents/{doc_id}/export",
                   params={"fmt": "excel", "layout": "statement"})
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    assert not [c for ws in wb.worksheets for row in ws.iter_rows() for c in row
                if c.data_type == "f"]
    notes = [c.comment.text for ws in wb.worksheets for row in ws.iter_rows() for c in row
             if c.comment]
    assert any("=SUM(x)" in note for note in notes)


def test_include_gates_analysis_sheets(client):
    import openpyxl

    doc_id = _extract(client, data=make_rich_pdf(), filename="rich.pdf")
    x = client.get(f"/api/v1/documents/{doc_id}/export",
                   params={"fmt": "excel", "layout": "statement", "include": "ratios"})
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    assert "Ratios" in wb.sheetnames
    assert "Disclosures" not in wb.sheetnames and "Note details" not in wb.sheetnames

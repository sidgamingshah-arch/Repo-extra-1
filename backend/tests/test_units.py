"""Source units/currency detection (Req 14) and presentation conversion at export, plus
localized free-form highlights (Req 21)."""
from __future__ import annotations

import io
import time

import pytest

pytest.importorskip("fitz")


def _units_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, h = A4
    c.setFont("Helvetica-Bold", 13); c.drawString(72, h - 55, "Balance Sheet")
    c.setFont("Helvetica", 9); c.drawString(72, h - 72, "(Amounts in HK$ million)")
    c.setFont("Helvetica", 10)
    c.drawString(72, h - 100, "Total assets      1,204")
    c.drawString(72, h - 120, "Total equity and liabilities      1,204")
    c.showPage(); c.save()
    return buf.getvalue()


def _await(client, doc_id):
    for _ in range(100):
        if client.get(f"/api/v1/documents/{doc_id}/run").json().get("status") == "succeeded":
            return
        time.sleep(0.05)
    raise AssertionError("not finished")


def test_source_units_detected():
    from app.services.documents import run_extraction

    doc, _ = run_extraction(_units_pdf(), filename="u.pdf")
    assert doc.unit_context is not None
    assert doc.unit_context.units_label == "million"
    assert int(doc.unit_context.scale_factor) == 1_000_000
    assert doc.unit_context.currency == "HKD"


def test_units_scale_only_converts_when_source_known():
    from app.services.export import units_scale

    src = {"scale_factor": 1e7, "currency": "INR", "units_label": "crore"}
    # crore source → present in thousands: ×1e7/1e3 = 1e4.
    assert units_scale(src, "thousands")[0] == 1e7 / 1e3
    # No target → no scaling. No source → never guess.
    assert units_scale(src, None)[0] == 1.0
    assert units_scale(None, "crore")[0] == 1.0


def test_export_applies_unit_conversion(client):
    import openpyxl

    doc_id = client.post("/api/v1/documents",
                         files={"file": ("u.pdf", _units_pdf(), "application/pdf")}).json()["id"]
    onts = client.get("/api/v1/ontologies").json()
    ont = next((o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v1"), onts[0])
    tpls = client.get("/api/v1/templates").json()
    tpl = next((t for t in tpls if t["template_key"] == ont["target_template_key"]), tpls[0])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    _await(client, doc_id)

    run = client.get(f"/api/v1/documents/{doc_id}/run").json()["result"]
    assert run["units"] and run["units"]["units_label"] == "million"

    # Present in thousands: 1,204 million → 1,204,000 thousand.
    x = client.get(f"/api/v1/documents/{doc_id}/export",
                   params={"fmt": "excel", "layout": "statement", "units": "thousands"})
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    joined = " | ".join(str(v) for row in wb["Balance Sheet"].iter_rows(values_only=True)
                        for v in row if v is not None)
    assert "1204000" in joined.replace(",", "") and "thousands" in joined.lower()


def test_free_notes_localized(client):
    from tests.fixtures.generate import make_rich_pdf

    doc_id = client.post("/api/v1/documents",
                         files={"file": ("rich.pdf", make_rich_pdf(), "application/pdf")}).json()["id"]
    onts = client.get("/api/v1/ontologies").json()
    ont = next((o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v1"), onts[0])
    tpls = client.get("/api/v1/templates").json()
    tpl = next((t for t in tpls if t["template_key"] == ont["target_template_key"]), tpls[0])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    _await(client, doc_id)

    fr = client.get(f"/api/v1/documents/{doc_id}/analysis", params={"locale": "fr"}).json()
    titles = [n["title"] for n in fr["notes"]]
    assert "Créances clients" in titles or "Liquidité" in titles

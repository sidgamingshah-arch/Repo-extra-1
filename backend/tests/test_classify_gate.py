"""Page classification recognises IFRS/HKFRS P&L phrasing (Req 19), and the integrity gate
is enforced at the API boundary (Req 17)."""
from __future__ import annotations

import io

import pytest

pytest.importorskip("fitz")


def _pnl_or_loss_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, h = A4
    c.setFont("Helvetica-Bold", 13)
    c.drawString(72, h - 60, "Consolidated Statement of Profit or Loss")
    c.setFont("Helvetica", 10)
    c.drawString(72, h - 90, "Revenue from operations      20,000")
    c.drawString(72, h - 110, "Operating profit      3,200")
    c.showPage(); c.save()
    return buf.getvalue()


def test_profit_or_loss_page_classifies_as_face():
    from app.core.models import PageKind
    from app.services.documents import run_extraction

    doc, _ = run_extraction(_pnl_or_loss_pdf(), filename="pnl.pdf")
    assert any(p.kind == PageKind.FACE for p in doc.pages), \
        "a 'Statement of Profit or Loss' page should classify as FACE"
    labels = {li.source_label for li in doc.line_items}
    assert any("Revenue" in l for l in labels)


def test_integrity_gate_blocks_extraction(client):
    # A non-document upload is detected as an unknown/corrupt format → BLOCKER integrity finding.
    up = client.post("/api/v1/documents",
                     files={"file": ("junk.pdf", b"this is not a pdf at all", "application/pdf")})
    assert up.status_code in (200, 201), up.text
    doc_id = up.json()["id"]
    report = up.json().get("integrity_report") or {}
    assert any(f.get("severity") == "blocker" for f in report.get("findings", []))
    r = client.post(f"/api/v1/documents/{doc_id}/extractions", json={})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "integrity_blocked"

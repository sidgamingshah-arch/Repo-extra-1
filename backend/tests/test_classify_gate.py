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


def test_real_shaped_annual_report_classifies_face_and_notes():
    """A realistic HKEX/IFRS report: the auditor's report (which mentions face phrases in prose)
    must NOT be FACE; the three consolidated statements ARE FACE; and the notes section — opened
    by '1 General information' with no 'Notes to…' banner — is captured as NOTES, so continuation
    note pages that mention 'profit or loss' in prose stay NOTES rather than being mis-read as face."""
    from app.core.models import PageKind
    from app.services.documents import run_extraction
    from tests.fixtures.generate import make_annual_report_pdf

    doc, _ = run_extraction(make_annual_report_pdf(), filename="ar.pdf")
    kinds = {p.index: p.kind for p in doc.pages}
    assert kinds[1] != PageKind.FACE, "the auditor's report is not a statement face"
    for i in (2, 3, 4):
        assert kinds[i] == PageKind.FACE, f"page {i} is a consolidated face statement"
    # Both note pages (5: '1 General information', 6: '18 Cash…') are captured as NOTES even
    # though the section opens without a 'Notes to…' banner.
    assert kinds[5] == PageKind.NOTES and kinds[6] == PageKind.NOTES
    assert len(doc.notes_pages()) >= 2


def test_chinese_hk_prc_titles_and_note_patterns():
    """HK-listed PRC entities often file bilingually: the classifier recognises the Chinese
    face-statement titles and note markers, and still rejects a Chinese prose mention that
    isn't a heading."""
    import re

    from app.stages.classify import (
        _NOTE_REF, _NOTES_HEADERS, _NUMBERED_HEADING, _face_title_at_top)

    assert _face_title_at_top("合并资产负债表\n货币资金 1,204")
    assert _face_title_at_top("綜合現金流量表")
    assert _face_title_at_top("合并利润表")
    # A Chinese prose sentence that merely mentions a statement name is not a title heading.
    assert not _face_title_at_top("独立核数师报告\n我们审计了合并利润表及合并现金流量表。")
    assert any(re.search(rx, "合并财务报表附注") for rx in _NOTES_HEADERS)
    assert _NUMBERED_HEADING.search("14. 現金及現金等價物")
    assert _NOTE_REF.search("附註 14") and _NOTE_REF.search("note 14")


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

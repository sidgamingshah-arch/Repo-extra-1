"""Ingest + integrity + classification on synthetic native fixtures."""
from __future__ import annotations

import pytest

from app.core.models import DocFormat, PageKind, Severity
from app.services.documents import analyze_document
from tests.fixtures.generate import make_multipage_pdf, make_native_pdf, make_xlsx

fitz = pytest.importorskip("fitz")  # PyMuPDF required for the native path


def test_native_pdf_is_routed_native_and_not_scanned():
    doc, _ = analyze_document(make_native_pdf(), "bs.pdf")
    assert doc.fmt == DocFormat.PDF
    assert len(doc.pages) == 1
    assert doc.pages[0].source_kind.value == "native"
    assert doc.integrity is not None
    assert not doc.integrity.has_blockers
    assert doc.integrity.scanned_page_ratio == 0.0


def test_multipage_classification_finds_face_and_notes():
    doc, _ = analyze_document(make_multipage_pdf(), "fs.pdf")
    kinds = {p.index: p.kind for p in doc.pages}
    assert kinds[0] == PageKind.FACE
    assert kinds[1] == PageKind.NOTES


def test_xlsx_ingest_and_hidden_sheet_finding():
    doc, _ = analyze_document(make_xlsx(), "model.xlsx")
    assert doc.fmt == DocFormat.XLSX
    assert len(doc.pages) >= 1
    codes = {f.check_id for f in doc.integrity.findings}
    assert "HIDDEN_SHEET" in codes


def test_corrupt_pdf_is_blocker():
    doc, _ = analyze_document(b"%PDF-1.4 broken garbage not a real pdf", "x.pdf")
    assert doc.integrity is not None
    assert doc.integrity.has_blockers
    assert any(f.severity == Severity.BLOCKER for f in doc.integrity.findings)

"""PDF extraction: native text layer (PyMuPDF) and the scanned/OCR path — both producing
line items with page + normalized-bbox provenance."""
from __future__ import annotations

import pytest

pytest.importorskip("fitz")

from tests.fixtures.generate import make_native_pdf


def test_native_pdf_extracts_values_with_bbox_provenance():
    from app.core.models.enums import Basis
    from app.services.documents import run_extraction

    doc, ctx = run_extraction(make_native_pdf(), filename="bs.pdf")
    assert doc.fmt.value == "pdf"
    labels = {li.source_label for li in doc.line_items}
    assert any("Trade receivables" in lbl for lbl in labels)

    tr = next(li for li in doc.line_items if "Trade receivables" in li.source_label)
    val = tr.get_value(Basis.CONSOLIDATED, period_label="current")
    assert val is not None and int(val.value) == 3410      # "3,410" parsed
    assert val.provenance is not None and val.provenance.page_index == 0
    assert val.provenance.bbox is not None                  # real click-to-source geometry
    assert val.provenance.source_kind == "native"
    assert tr.note_number == "15"                           # "Note 15" captured, not a value


def test_scanned_page_routes_through_ocr_port():
    """A scanned page is rasterized and sent to the configured OCR provider; its words
    (already normalized) reconstruct into line items with source_kind 'ocr'."""
    from app.config import get_settings
    from app.core.models.document import DocumentModel, PageSource
    from app.core.models.enums import DocFormat, PageKind, PageSourceKind
    from app.core.models.geometry import BBox
    from app.core.stage import PipelineContext
    from app.ports.registry import registry
    from app.services.pdf_extract import extract_pdf

    class _FakeOcr:
        id = "fakeocr"

        def recognize(self, image_bytes, *, lang="en"):
            return {"words": [
                {"text": "Cash", "bbox": BBox(x0=0.10, y0=0.20, x1=0.20, y1=0.23), "confidence": 0.99},
                {"text": "and", "bbox": BBox(x0=0.21, y0=0.20, x1=0.26, y1=0.23), "confidence": 0.99},
                {"text": "equivalents", "bbox": BBox(x0=0.27, y0=0.20, x1=0.40, y1=0.23), "confidence": 0.99},
                {"text": "1,204", "bbox": BBox(x0=0.80, y0=0.20, x1=0.90, y1=0.23), "confidence": 0.98},
            ], "angle": 0.0}

        def detect_orientation(self, image_bytes):
            return 0.0

    registry.register("ocr", "fakeocr", _FakeOcr)
    settings = get_settings()
    prev = settings.ocr.engine
    settings.ocr.engine = "fakeocr"
    try:
        doc = DocumentModel(filename="scan.pdf", content_hash="h1")
        doc.fmt = DocFormat.PDF
        doc.pages = [PageSource(index=0, source_kind=PageSourceKind.SCANNED, kind=PageKind.FACE)]
        ctx = PipelineContext(raw_bytes=make_native_pdf())
        added = extract_pdf(make_native_pdf(), doc, ctx)
        assert added >= 1
        item = doc.line_items[0]
        assert "Cash" in item.source_label
        ev = next(iter(item.values.values()))
        assert int(ev.value) == 1204
        assert ev.provenance.source_kind == "ocr" and ev.provenance.bbox is not None
    finally:
        settings.ocr.engine = prev

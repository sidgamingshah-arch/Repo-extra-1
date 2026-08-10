"""Standalone image uploads extract via the OCR port (Req 1), and produce a clear
'OCR not configured' outcome (no silent empty success) when the engine is the stub."""
from __future__ import annotations


class _FakeOcr:
    id = "fakeimg"

    def recognize(self, image_bytes, *, lang="en"):
        from app.core.models.geometry import BBox
        return {"words": [
            {"text": "Cash", "bbox": BBox(x0=0.10, y0=0.20, x1=0.20, y1=0.23), "confidence": 0.99},
            {"text": "and", "bbox": BBox(x0=0.21, y0=0.20, x1=0.26, y1=0.23), "confidence": 0.99},
            {"text": "equivalents", "bbox": BBox(x0=0.27, y0=0.20, x1=0.40, y1=0.23), "confidence": 0.99},
            {"text": "1,204", "bbox": BBox(x0=0.80, y0=0.20, x1=0.90, y1=0.23), "confidence": 0.98},
        ], "angle": 0.0}

    def detect_orientation(self, image_bytes):
        return 0.0


def _doc():
    from app.core.models.document import DocumentModel
    from app.core.models.enums import DocFormat
    doc = DocumentModel(filename="scan.png", content_hash="img1")
    doc.fmt = DocFormat.IMAGE
    return doc


def test_image_extracts_via_ocr_port():
    from app.config import get_settings
    from app.core.stage import PipelineContext
    from app.ports.registry import registry
    from app.services.pdf_extract import extract_image

    registry.register("ocr", "fakeimg", _FakeOcr)
    settings = get_settings()
    prev = settings.ocr.engine
    settings.ocr.engine = "fakeimg"
    try:
        doc = _doc()
        added = extract_image(b"\x89PNG_fake_bytes", doc, PipelineContext(raw_bytes=b"x"))
        assert added >= 1 and doc.line_items
        item = doc.line_items[0]
        assert "Cash" in item.source_label
        ev = next(iter(item.values.values()))
        assert int(ev.value) == 1204 and ev.provenance.source_kind == "ocr"
    finally:
        settings.ocr.engine = prev


def test_image_without_ocr_is_not_a_silent_success():
    from app.config import get_settings
    from app.core.stage import PipelineContext
    from app.services.pdf_extract import extract_image

    settings = get_settings()
    prev = settings.ocr.engine
    settings.ocr.engine = "stub"
    try:
        doc = _doc()
        ctx = PipelineContext(raw_bytes=b"x")
        added = extract_image(b"\x89PNG_fake_bytes", doc, ctx)
        assert added == 0 and not doc.line_items
        assert any("image_no_ocr" in m for m in ctx.logs)   # explicit "OCR not configured"
    finally:
        settings.ocr.engine = prev

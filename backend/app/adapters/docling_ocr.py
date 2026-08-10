"""Docling adapter for the OcrProvider port (install the ``docling`` extra).

Docling (https://github.com/docling-project/docling) is a free, open-source, pip-installable
document-understanding toolkit — no system binary, no cloud service. It does layout analysis,
OCR (RapidOCR / EasyOCR / Tesseract backends) and table-structure recovery, which makes it a
strong "free OCR" option for scanned filings.

This adapter converts a rasterized page image and maps Docling's text items to the
``OcrProvider`` contract: word-level tokens with **normalized [0,1] top-left** bounding boxes,
so they feed the same ``row_reconstruct`` logic as the native-PDF and PaddleOCR paths.

Lazy: importing this module needs neither Docling nor its models — the converter is built on
first use, so the app and tests run without the heavy dependency.
"""
from __future__ import annotations

import io

from app.adapters._structured import LlmConfigError  # reused: "adapter selected but unusable"
from app.core.models.geometry import BBox
from app.ports.ocr import OcrResult, OcrWord


def _split_into_words(text: str, box: BBox, confidence: float = 1.0) -> list[OcrWord]:
    """Split a Docling text item into word tokens, distributing its bbox horizontally by
    character position. Docling returns line/span-level items; the reconstruction step needs
    word-level tokens to separate the label column from the value columns, so we approximate
    each word's x-extent from where it sits in the string. y is shared (same line)."""
    tokens = text.split()
    if not tokens:
        return []
    if len(tokens) == 1:
        return [{"text": tokens[0], "bbox": box, "confidence": confidence}]

    total = max(len(text), 1)
    span = max(box.x1 - box.x0, 0.0)
    words: list[OcrWord] = []
    pos = 0
    for tok in tokens:
        start = text.index(tok, pos)
        end = start + len(tok)
        pos = end
        x0 = box.x0 + span * (start / total)
        x1 = box.x0 + span * (end / total)
        words.append({
            "text": tok,
            "bbox": BBox(x0=x0, y0=box.y0, x1=min(x1, 1.0), y1=box.y1),
            "confidence": confidence,
        })
    return words


class DoclingOcrProvider:
    id = "docling"

    def __init__(self, settings=None):
        from app.config import get_settings

        self._settings = settings or get_settings()
        self._converter = None

    def _converter_or_raise(self):
        if self._converter is not None:
            return self._converter
        try:
            from docling.document_converter import DocumentConverter
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on the docling extra
            raise LlmConfigError(
                "Docling is not installed. Run: pip install -e \".[docling]\""
            ) from exc
        self._converter = DocumentConverter()
        return self._converter

    def recognize(self, image_bytes: bytes, *, lang: str = "en") -> OcrResult:  # pragma: no cover - needs docling + models
        from docling.datamodel.base_models import DocumentStream

        converter = self._converter_or_raise()
        source = DocumentStream(name="page.png", stream=io.BytesIO(image_bytes))
        doc = converter.convert(source).document

        words: list[OcrWord] = []
        for item in getattr(doc, "texts", []) or []:
            text = getattr(item, "text", "") or ""
            for prov in (getattr(item, "prov", None) or []):
                box = self._normalize_bbox(doc, prov)
                if box is not None:
                    words.extend(_split_into_words(text, box))
        return {"words": words, "angle": 0.0}

    @staticmethod
    def _normalize_bbox(doc, prov) -> BBox | None:  # pragma: no cover - needs docling types
        """Map a Docling provenance bbox to a normalized top-left BBox using the page size."""
        page = getattr(doc, "pages", {}).get(getattr(prov, "page_no", 1))
        size = getattr(page, "size", None)
        if size is None:
            return None
        pw, ph = float(size.width), float(size.height)
        if pw <= 0 or ph <= 0:
            return None
        bbox = prov.bbox
        # Docling BoundingBox may originate bottom-left; convert to top-left when possible.
        to_tl = getattr(bbox, "to_top_left_origin", None)
        if callable(to_tl):
            bbox = to_tl(page_height=ph)
        x0, x1 = sorted((float(bbox.l), float(bbox.r)))
        y0, y1 = sorted((float(bbox.t), float(bbox.b)))
        return BBox(x0=max(x0 / pw, 0.0), y0=max(y0 / ph, 0.0),
                    x1=min(x1 / pw, 1.0), y1=min(y1 / ph, 1.0))

    def detect_orientation(self, image_bytes: bytes) -> float:
        return 0.0

"""PaddleOCR adapter for the OcrProvider port (install the ``ocr`` extra).

Lazy: importing this module needs neither PaddleOCR nor its models — the engine is
constructed on first use, so the app and tests run without the heavy dependency. Bounding
boxes are returned **normalized** to [0,1] in the image's top-left space, matching the
BBox contract the reconstruction path expects.
"""
from __future__ import annotations

from app.adapters._structured import LlmConfigError  # reused: "adapter selected but unusable"
from app.core.models.geometry import BBox
from app.ports.ocr import OcrResult


class PaddleOcrProvider:
    id = "paddleocr"

    def __init__(self, settings=None):
        from app.config import get_settings

        self._settings = settings or get_settings()
        self._engine = None

    def _engine_or_raise(self):
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on the ocr extra
            raise LlmConfigError(
                "PaddleOCR is not installed. Run: pip install -e \".[ocr]\""
            ) from exc
        langs = self._settings.ocr.languages or ["en"]
        self._engine = PaddleOCR(use_angle_cls=True, lang=langs[0], show_log=False)
        return self._engine

    def recognize(self, image_bytes: bytes, *, lang: str = "en") -> OcrResult:
        import numpy as np
        from PIL import Image
        import io

        engine = self._engine_or_raise()
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        arr = np.array(img)
        raw = engine.ocr(arr, cls=True)

        words: list[dict] = []
        for line in (raw[0] if raw and raw[0] else []):
            box, (text, conf) = line[0], line[1]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            words.append({
                "text": text,
                "bbox": BBox(x0=min(xs) / w, y0=min(ys) / h, x1=max(xs) / w, y1=max(ys) / h),
                "confidence": float(conf),
            })
        return {"words": words, "angle": 0.0}

    def detect_orientation(self, image_bytes: bytes) -> float:
        return 0.0

"""OCR provider port."""
from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable

from app.core.models import BBox


class OcrWord(TypedDict):
    text: str
    bbox: BBox
    confidence: float


class OcrResult(TypedDict):
    words: list[OcrWord]
    angle: float


@runtime_checkable
class OcrProvider(Protocol):
    id: str

    def recognize(self, image_bytes: bytes, *, lang: str = "en") -> OcrResult: ...

    def detect_orientation(self, image_bytes: bytes) -> float: ...

"""Table-structure provider port (PP-Structure / Table-Transformer)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.models import Table
from .ocr import OcrResult


@runtime_checkable
class TableStructureProvider(Protocol):
    id: str

    def extract_tables(self, image_bytes: bytes, words: OcrResult, *,
                       page_index: int) -> list[Table]: ...

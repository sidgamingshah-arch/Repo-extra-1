"""The ``Table`` model — the convergence point of the pipeline.

Native pages (pdfplumber rulings / PyMuPDF word coords) and scanned pages
(OCR + table-structure model) both reconstruct into this *same* model, so every
downstream stage is source-agnostic (it never knows or cares whether a cell came
from a text layer or from OCR).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .geometry import BBox


class Cell(BaseModel):
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str = ""
    bbox: BBox | None = None
    ocr_conf: float = 1.0
    is_numeric: bool = False


class Table(BaseModel):
    page_index: int
    bbox: BBox | None = None
    n_rows: int = 0
    n_cols: int = 0
    cells: list[Cell] = Field(default_factory=list)
    header_rows: list[int] = Field(default_factory=list)
    label_col: int = 0
    source_kind: str = "native"   # native | ocr

    def cell_at(self, row: int, col: int) -> Cell | None:
        for c in self.cells:
            if c.row == row and c.col == col:
                return c
        return None

    def row_cells(self, row: int) -> list[Cell]:
        return sorted((c for c in self.cells if c.row == row), key=lambda c: c.col)

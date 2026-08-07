"""Geometry & provenance.

Bounding boxes are stored **normalized** to [0..1] in the *original* page's
top-left coordinate space. This is the single most important choice for the
side-by-side hyperlink feature: normalized boxes survive any zoom / DPI / render
scale on the frontend, and normalizing (including the PDF y-flip) server-side means
the client never performs coordinate math beyond ``box * renderedSize``.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class BBox(BaseModel):
    """Normalized bounding box, origin top-left, y-down, values in [0, 1]."""

    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("BBox requires x1 >= x0 and y1 >= y0")
        return self

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def union(self, other: "BBox") -> "BBox":
        return BBox(
            x0=min(self.x0, other.x0),
            y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1),
            y1=max(self.y1, other.y1),
        )


class Transform(BaseModel):
    """A pre-processing transform (deskew/rotate/scale) applied before OCR.

    Recorded so provenance can be mapped back to the *original* page space.
    """

    kind: str                       # "rotate" | "deskew" | "scale" | "crop"
    params: dict[str, float] = Field(default_factory=dict)


class Provenance(BaseModel):
    """Where an extracted value came from.

    Paginated sources (PDF/scans) anchor on ``page_index`` + a normalized ``bbox``.
    Spreadsheet sources (Excel) have no pixel geometry, so ``bbox`` is omitted and the
    exact origin is the ``sheet`` + ``cell`` reference (e.g. sheet "P&L", cell "C14").
    Either way the value is anchored to a precise, verifiable source location — which is
    what lets the LLM *reference* facts by id while the value + provenance stay
    deterministic (see docs/architecture: grounded extraction)."""

    document_id: str | None = None
    page_index: int
    bbox: BBox | None = None
    label_bbox: BBox | None = None
    value_bbox: BBox | None = None
    # Spreadsheet-cell provenance (non-paginated sources).
    sheet: str | None = None
    cell: str | None = None          # A1-style value cell, e.g. "C14"
    label_cell: str | None = None    # A1-style cell of the row label
    text_snippet: str | None = None
    source_kind: str = "native"      # native | ocr | spreadsheet
    producer: str | None = None      # "<stage>:<adapter>@<version>"
    transforms: list[Transform] = Field(default_factory=list)

    def merged(self, others: list["Provenance"]) -> "Provenance":
        """Aggregate provenance for a derived value (e.g. a reconciled face figure).

        Keeps this provenance's page/bbox as the anchor and widens the bbox to cover
        all contributing regions on the same page.
        """
        if self.bbox is None:
            return self
        box = self.bbox
        for o in others:
            if o.page_index == self.page_index and o.bbox is not None:
                box = box.union(o.bbox)
        return self.model_copy(update={"bbox": box})

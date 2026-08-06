"""The document model that flows through the pipeline.

Each stage *enriches* this immutable-ish model rather than mutating external state,
which makes stages independently testable and re-runnable and gives provenance for
free (each enrichment records which stage/adapter produced it).
"""
from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import DocFormat, PageKind, PageSourceKind
from .integrity import IntegrityReport
from .line_item import FaceNoteLink, LineItem, NotesTable
from .table import Table


class PageSource(BaseModel):
    index: int
    kind: PageKind = PageKind.UNKNOWN
    source_kind: PageSourceKind = PageSourceKind.NATIVE
    width_pt: float = 0.0
    height_pt: float = 0.0
    dpi: int | None = None
    rotation: int = 0
    text_char_count: int = 0
    text_area_coverage: float = 0.0
    image_area_coverage: float = 0.0
    classification_confidence: float | None = None
    classification_evidence: list[str] = Field(default_factory=list)


class DocumentModel(BaseModel):
    """The single artifact enriched stage-by-stage."""

    id: UUID = Field(default_factory=uuid4)
    filename: str = ""
    content_hash: str | None = None
    fmt: DocFormat = DocFormat.UNKNOWN
    object_key: str | None = None
    locale: str | None = None                 # detected primary locale

    pages: list[PageSource] = Field(default_factory=list)
    integrity: IntegrityReport | None = None
    tables: list[Table] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    notes: list[NotesTable] = Field(default_factory=list)
    links: list[FaceNoteLink] = Field(default_factory=list)

    def face_pages(self) -> list[PageSource]:
        return [p for p in self.pages if p.kind == PageKind.FACE]

    def notes_pages(self) -> list[PageSource]:
        return [p for p in self.pages if p.kind == PageKind.NOTES]

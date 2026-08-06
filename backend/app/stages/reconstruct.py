"""Table-reconstruction stage.

Native pages reconstruct tables from pdfplumber rulings / PyMuPDF word coords;
scanned pages route through the OCR + table-structure adapters. Both converge on the
same ``Table`` model so downstream stages are source-agnostic.

Scaffold: focuses face/notes pages only (Requirement 19). The native pdfplumber path
and the OCR path are TODO — wired to the ``pdf`` and ``ocr`` extras respectively.
"""
from __future__ import annotations

from app.core.models import DocumentModel, PageKind, PageSourceKind
from app.core.stage import PipelineContext


class ReconstructStage:
    name = "reconstruct"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        # Only reconstruct pages worth extracting (face + notes) — Requirement 19.
        target = [p for p in doc.pages if p.kind in (PageKind.FACE, PageKind.NOTES)]
        ctx.log(f"reconstruct:target_pages={len(target)}")
        for p in target:
            if p.source_kind == PageSourceKind.SCANNED:
                # TODO: ocr = ctx.registry.get("ocr", ctx.settings.ocr_provider)
                #       tables = ctx.registry.get("table", ...).extract_tables(...)
                ctx.log(f"reconstruct:page={p.index}:needs_ocr")
            else:
                # TODO: native table reconstruction via pdfplumber rulings.
                ctx.log(f"reconstruct:page={p.index}:native_todo")
        return doc

"""PDF → line items. Native pages use the PyMuPDF text layer; scanned pages route through
the configured OCR provider. Both converge on the shared word→line-item reconstruction, so
every value carries page + normalized-bbox provenance regardless of source.
"""
from __future__ import annotations

from app.core.models.enums import PageKind, PageSourceKind
from app.core.models.geometry import BBox
from app.core.stage import PipelineContext
from app.services.row_reconstruct import Word, build_line_items


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _native_words(page, w: float, h: float) -> list[Word]:
    out: list[Word] = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        if not text.strip():
            continue
        out.append(Word(text=text, bbox=BBox(
            x0=_clamp(x0 / w), y0=_clamp(y0 / h), x1=_clamp(x1 / w), y1=_clamp(y1 / h))))
    return out


def extract_pdf(data: bytes, doc, ctx: PipelineContext) -> int:
    """Extract line items from a PDF into ``doc.line_items``. Returns the count added."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        ctx.log("extract:pymupdf_missing")
        return 0
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # corruption already surfaced by the integrity stage
        ctx.log(f"extract:pdf_open_failed:{exc}")
        return 0

    # Prefer statement pages (face + notes). Also include SCANNED pages even if they didn't
    # classify — a scanned page has no text layer to match a title against, so it would
    # otherwise be dropped before ever reaching the OCR path. Fall back to all pages if
    # nothing was classified at all.
    targets = [p for p in doc.pages
               if p.kind in (PageKind.FACE, PageKind.NOTES)
               or p.source_kind == PageSourceKind.SCANNED]
    if not targets:
        targets = list(doc.pages)

    ocr = None
    added = 0
    ordinal = len(doc.line_items)
    for ps in targets:
        if ps.index >= pdf.page_count:
            continue
        page = pdf[ps.index]
        rect = page.rect
        w, h = max(rect.width, 1.0), max(rect.height, 1.0)

        if ps.source_kind == PageSourceKind.SCANNED:
            if ocr is None:                      # resolve the OCR provider lazily, once
                ocr = _resolve_ocr(ctx)
            if ocr is None:
                ctx.log(f"extract:page={ps.index}:scanned_no_ocr")
                continue
            words = _ocr_words_for(page, ocr, ctx)
            source_kind = "ocr"
        else:
            words = _native_words(page, w, h)
            source_kind = "native"

        if not words:
            continue
        # Notes pages → note detail tables (the breakdowns behind the face figures); every
        # other page → face line items. Both keep page + bbox provenance.
        if ps.kind == PageKind.NOTES:
            from app.services.notes_extract import extract_note_tables

            tables = extract_note_tables(words, page_index=ps.index,
                                         document_id=doc.content_hash, source_kind=source_kind)
            doc.notes.extend(tables)
            continue
        items, ordinal = build_line_items(
            words, page_index=ps.index, document_id=doc.content_hash,
            source_kind=source_kind, ordinal_start=ordinal)
        doc.line_items.extend(items)
        added += len(items)
    ctx.log(f"extract:pdf_line_items={added} note_tables={len(doc.notes)}")
    return added


def _resolve_ocr(ctx: PipelineContext):
    engine = ctx.settings.ocr.engine
    if engine == "stub":
        return None
    try:
        return ctx.registry.get("ocr", engine)
    except Exception as exc:
        ctx.log(f"extract:ocr_unavailable({exc})")
        return None


def _ocr_words_for(page, ocr, ctx: PipelineContext) -> list[Word]:
    """Rasterize a page and OCR it; OCR bboxes are already normalized (see OcrProvider)."""
    try:
        import fitz  # noqa: F401 - page already comes from fitz

        pix = page.get_pixmap(dpi=ctx.settings.ocr.dpi)
        png = pix.tobytes("png")
        result = ocr.recognize(png, lang=(ctx.settings.ocr.languages or ["en"])[0])
    except NotImplementedError:
        ctx.log("extract:ocr_not_implemented")
        return []
    except Exception as exc:
        ctx.log(f"extract:ocr_failed({exc})")
        return []
    return [Word(text=w["text"], bbox=w["bbox"]) for w in result.get("words", [])]

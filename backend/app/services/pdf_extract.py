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

    # Honour an explicit user page scope (from the Page Scope screen): keep only pages the
    # user chose to include. An empty selection is treated as "no restriction" so a stray
    # empty list can never silently extract nothing.
    if ctx.included_pages:
        scoped = [p for p in targets if p.index in ctx.included_pages]
        if scoped:
            targets = scoped
            ctx.log(f"extract:page_scope_applied={sorted(ctx.included_pages)}")

    number_format = _resolve_number_format(ctx, doc)
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
        # ``ps.statement`` (from the classifier) is what tells the reconstructor that a page is a
        # component matrix rather than a two-column comparative; ``ctx.log`` records the cases
        # where a matrix page could not be attributed and was skipped.
        items, ordinal = build_line_items(
            words, page_index=ps.index, document_id=doc.content_hash,
            source_kind=source_kind, ordinal_start=ordinal, number_format=number_format,
            statement=ps.statement, log=ctx.log)
        doc.line_items.extend(items)
        added += len(items)
    ctx.log(f"extract:pdf_line_items={added} note_tables={len(doc.notes)}")
    return added


def extract_image(data: bytes, doc, ctx: PipelineContext) -> int:
    """Extract line items from a standalone image (PNG/JPG/TIFF) by sending the bytes straight
    to the configured OCR provider, then reconstructing rows exactly like a scanned PDF page.
    With no OCR engine configured (the default ``stub``), logs a clear 'OCR not configured'
    marker and adds nothing — never a silent empty success."""
    ocr = _resolve_ocr(ctx)
    if ocr is None:
        ctx.log("extract:image_no_ocr(configure an OCR engine; default is stub)")
        return 0
    lang = (ctx.settings.ocr.languages or ["en"])[0]
    try:
        result = ocr.recognize(data, lang=lang)
    except NotImplementedError:
        ctx.log("extract:image_ocr_not_implemented")
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log(f"extract:image_ocr_failed({exc})")
        return 0
    words = [Word(text=w["text"], bbox=w["bbox"]) for w in result.get("words", [])]
    if not words:
        ctx.log("extract:image_ocr_no_words")
        return 0
    items, _ = build_line_items(words, page_index=0, document_id=doc.content_hash,
                                source_kind="ocr")
    doc.line_items.extend(items)
    ctx.log(f"extract:image_line_items={len(items)}")
    return len(items)


def _resolve_number_format(ctx: PipelineContext, doc):
    """The locale ``NumberFormat`` for value parsing: the ontology's per-locale format keyed
    by the document's detected locale. Returns None for English or an unset locale so the fast
    US regex path is used unchanged — locale-aware parsing (EU decimal-comma, Indian grouping)
    activates only for a non-English document that has a declared format."""
    loc = doc.locale
    if not loc or loc == "en":
        return None
    ontology = getattr(ctx, "ontology", None)
    if ontology is None:
        return None
    by_locale = getattr(ontology, "number_format_by_locale", None) or {}
    return by_locale.get(loc)


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

"""Ingest & format routing stage.

Detects the document format from magic bytes (not just the extension) and, for PDFs,
performs **per-page** native-vs-scanned detection — mixed documents (native text with
a scanned insert) are the norm, so routing is never a document-level flag.
"""
from __future__ import annotations

from app.core.models import DocFormat, DocumentModel, PageKind, PageSource, PageSourceKind
from app.core.stage import PipelineContext


def detect_format(data: bytes, filename: str = "") -> DocFormat:
    if data[:4] == b"%PDF":
        return DocFormat.PDF
    if data[:2] == b"PK":  # zip container → xlsx/docx
        if filename.lower().endswith((".xlsx", ".xlsm")):
            return DocFormat.XLSX
        return DocFormat.XLSX
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE2 → legacy xls
        return DocFormat.XLS
    if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff":
        return DocFormat.IMAGE
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return DocFormat.XLSX
    if lower.endswith(".xls"):
        return DocFormat.XLS
    if lower.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
        return DocFormat.IMAGE
    if lower.endswith((".htm", ".html")):
        return DocFormat.HTML
    return DocFormat.UNKNOWN


class IngestStage:
    name = "ingest"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        data = ctx.raw_bytes
        if data is None and doc.object_key and ctx.object_store is not None:
            data = ctx.object_store.get(doc.object_key)
            ctx.raw_bytes = data
        if not data:
            ctx.log("ingest:no_bytes")
            return doc

        doc.fmt = detect_format(data, doc.filename)
        ctx.log(f"ingest:format={doc.fmt.value}")

        if doc.fmt == DocFormat.PDF:
            self._ingest_pdf(doc, data, ctx)
        elif doc.fmt in (DocFormat.XLSX,):
            self._ingest_excel(doc, data, ctx)
        elif doc.fmt == DocFormat.IMAGE:
            doc.pages = [PageSource(index=0, source_kind=PageSourceKind.SCANNED,
                                    kind=PageKind.UNKNOWN)]
        return doc

    # -- PDF --------------------------------------------------------------

    def _ingest_pdf(self, doc: DocumentModel, data: bytes, ctx: PipelineContext) -> None:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            ctx.log("ingest:pymupdf_missing")
            return

        try:
            pdf = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 - corruption surfaced by integrity stage
            ctx.log(f"ingest:pdf_open_failed:{exc}")
            return

        s = ctx.settings
        pages: list[PageSource] = []
        for i, page in enumerate(pdf):
            rect = page.rect
            page_area = max(rect.width * rect.height, 1.0)
            text = page.get_text("text") or ""
            char_count = len(text.strip())

            # Text coverage from span rects.
            text_area = 0.0
            try:
                d = page.get_text("dict")
                for block in d.get("blocks", []):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            x0, y0, x1, y1 = span["bbox"]
                            text_area += max(0.0, (x1 - x0)) * max(0.0, (y1 - y0))
            except Exception:  # noqa: BLE001
                pass
            text_cov = text_area / page_area

            # Image coverage.
            image_area = 0.0
            try:
                for img in page.get_images(full=True):
                    for r in page.get_image_rects(img[0]):
                        image_area += r.width * r.height
            except Exception:  # noqa: BLE001
                pass
            image_cov = min(image_area / page_area, 1.0)

            if char_count > s.native_min_chars and text_cov > s.native_min_text_coverage:
                src = PageSourceKind.MIXED if image_cov > 0.5 else PageSourceKind.NATIVE
            elif image_cov > 0.5:
                src = PageSourceKind.SCANNED
            else:
                # very sparse page (blank / mostly whitespace) — treat as native, flagged by integrity
                src = PageSourceKind.NATIVE

            pages.append(PageSource(
                index=i,
                source_kind=src,
                width_pt=rect.width,
                height_pt=rect.height,
                rotation=page.rotation,
                text_char_count=char_count,
                text_area_coverage=round(text_cov, 4),
                image_area_coverage=round(image_cov, 4),
            ))
        doc.pages = pages
        pdf.close()
        ctx.log(f"ingest:pages={len(pages)}")

    # -- Excel ------------------------------------------------------------

    def _ingest_excel(self, doc: DocumentModel, data: bytes, ctx: PipelineContext) -> None:
        try:
            import io

            import openpyxl
        except ImportError:
            ctx.log("ingest:openpyxl_missing")
            return
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as exc:  # noqa: BLE001
            ctx.log(f"ingest:xlsx_open_failed:{exc}")
            return
        # One "page" per worksheet; Excel is always native.
        doc.pages = [
            PageSource(index=i, source_kind=PageSourceKind.NATIVE, kind=PageKind.UNKNOWN)
            for i, _ in enumerate(wb.sheetnames)
        ]
        ctx.log(f"ingest:sheets={len(doc.pages)}")
        wb.close()

"""Document endpoints: upload (+ upfront integrity/classification) and fetch."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db, object_store
from app.ports.object_store import LocalObjectStore
from app.security import Permission, current_principal, require
from app.services.documents import analyze_document, content_hash

router = APIRouter(prefix="/documents", tags=["documents"])


def _tag_for(fmt: str) -> str:
    return {"image": "Scanned", "pdf": "Native", "xlsx": "Native"}.get(fmt, "Native")


def _human_size(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, n // 1024)} KB"


def _to_source_doc(row) -> dict:
    """Map a stored Document to the frontend SourceDoc shape used by the Upload list."""
    name = row.filename or "document"
    ext = (name.rsplit(".", 1)[-1] if "." in name else row.fmt or "").upper()[:4]
    return {
        "id": row.id,
        "name": name,
        "ext": ext or "DOC",
        "meta": f"{row.page_count} pages · {_human_size(row.byte_size)}",
        "tag": _tag_for(row.fmt),
    }


@router.get("", dependencies=[Depends(current_principal)])
def list_documents(session: Session = Depends(db)) -> dict:
    """Real uploaded documents, most recent first (Upload screen list)."""
    from app.db.models import Document

    rows = session.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
    return {"documents": [_to_source_doc(r) for r in rows]}


@router.post("", status_code=201, dependencies=[Depends(require(Permission.DOCUMENTS_MANAGE))])
async def upload_document(
    file: UploadFile = File(...),
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> dict:
    from app.db.models import Document

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    digest = content_hash(data)
    existing = session.execute(
        select(Document).where(Document.content_hash == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return {"id": existing.id, "status": existing.status,
                "content_hash": digest, "duplicate_of": existing.id,
                "page_count": existing.page_count,
                "integrity_report": existing.integrity_report}

    doc_model, _ctx = analyze_document(data, filename=file.filename or "")
    object_key = store.put_bytes(data)

    row = Document(
        filename=file.filename or "",
        content_hash=digest,
        byte_size=len(data),
        fmt=doc_model.fmt.value,
        object_key=object_key,
        status="integrity_checked",
        locale=doc_model.locale,
        page_count=len(doc_model.pages),
        integrity_report=doc_model.integrity.model_dump(mode="json") if doc_model.integrity else None,
    )
    session.add(row)
    session.commit()

    return {
        "id": row.id,
        "status": row.status,
        "content_hash": digest,
        "duplicate_of": None,
        "format": row.fmt,
        "locale": row.locale,
        "page_count": row.page_count,
        "pages": [p.model_dump(mode="json") for p in doc_model.pages],
        "integrity_report": row.integrity_report,
    }


_CHECK_TITLES = {
    "UNKNOWN_FORMAT": "Unrecognized file format",
    "CORRUPT": "File appears corrupt",
    "PASSWORD_PROTECTED": "Password-protected document",
    "ENCRYPTED": "Encrypted document",
    "MIXED_SCAN": "Mixed scanned and native pages",
    "ROTATED_PAGE": "Rotated page",
    "INCONSISTENT_DIMENSIONS": "Inconsistent page dimensions",
    "HIDDEN_SHEET": "Hidden worksheet",
    "NO_PAGES": "No pages found",
    "BLANK_PAGE": "Blank page",
}
# Map pipeline severities → the frontend's issue severity + score penalty.
_SEV = {
    "blocker": ("low", 35), "error": ("low", 25),
    "warning": ("warn", 8), "info": ("ok", 2),
}


def _pct_label(ratio: float) -> str:
    """Percent label that never reads a contradictory '0%' for a non-zero ratio."""
    pct = round(ratio * 100)
    if ratio > 0 and pct == 0:
        return "<1%"
    return f"{pct}%"


def _serialize_document_integrity(row) -> dict:
    """Map a stored IntegrityReport (per uploaded document) into the IntegrityResponse the
    Document Integrity screen renders — so a real uploaded file surfaces its own pre-flight
    results, not the demo project's."""
    report = row.integrity_report
    # No stored report → the file was never actually checked. Do NOT fabricate an all-clear;
    # surface an explicit "not analyzed" state so an unchecked file is never shown as clean.
    if not report:
        return {
            "score": 0, "grade": "Not analyzed",
            "summary": "No integrity report is available for this document. Re-upload to run the pre-flight checks.",
            "stats": [
                {"label": "Pages", "value": str(row.page_count or 0), "sub": "detected", "tone": "neutral"},
                {"label": "Document type", "value": "Unknown", "sub": "native vs scanned", "tone": "warn"},
                {"label": "Scanned pages", "value": "—", "sub": "need OCR", "tone": "neutral"},
                {"label": "Issues", "value": "—", "sub": "not checked", "tone": "warn"},
            ],
            "issues": [{"title": "Integrity not available",
                        "detail": "This document has no stored pre-flight report.",
                        "pages": "All", "note": "UNKNOWN", "status": "Not analyzed", "severity": "warn"}],
        }

    findings = report.get("findings", []) or []
    page_count = report.get("page_count", row.page_count or 0)
    scanned_ratio = float(report.get("scanned_page_ratio", 0.0) or 0.0)

    score = 100
    has_blocker = False
    issues = []
    for f in findings:
        sev = str(f.get("severity", "info"))
        fe_sev, penalty = _SEV.get(sev, ("ok", 2))
        score -= penalty
        # Only BLOCKER gates extraction — matches IntegrityReport.has_blockers and the
        # pipeline's gating semantics (ERROR/WARNING annotate but never halt the run).
        blocking = sev == "blocker"
        has_blocker = has_blocker or blocking
        pidx = f.get("page_index")
        issues.append({
            "title": _CHECK_TITLES.get(f.get("check_id", ""), str(f.get("check_id", "Issue")).replace("_", " ").title()),
            "detail": f.get("message", ""),
            "pages": f"p.{pidx + 1}" if isinstance(pidx, int) else "All",
            "note": sev.upper(),
            "status": "Blocking" if blocking else "Advisory",
            "severity": fe_sev,
        })
    score = max(0, min(100, score))

    if has_blocker:
        grade, summary = "Blocked", "Resolve the blocking issues before extracting."
    elif score >= 90:
        grade, summary = "Ready to extract", "No material issues detected."
    elif score >= 70:
        grade, summary = "Minor issues", "Proceed with caution — review the flagged items."
    else:
        grade, summary = "Needs attention", "Several issues detected — review before extracting."

    kind = "Native" if scanned_ratio == 0 else "Scanned" if scanned_ratio >= 0.99 else "Mixed"
    stats = [
        {"label": "Pages", "value": str(page_count), "sub": "detected", "tone": "neutral"},
        {"label": "Document type", "value": kind, "sub": "native vs scanned",
         "tone": "ok" if kind == "Native" else "warn"},
        {"label": "Scanned pages", "value": _pct_label(scanned_ratio),
         "sub": "need OCR", "tone": "warn" if scanned_ratio > 0 else "ok"},
        {"label": "Issues", "value": str(len(findings)), "sub": "found",
         "tone": "warn" if findings else "ok"},
    ]
    if not issues:
        issues = [{"title": "No issues detected", "detail": "The document passed all integrity checks.",
                   "pages": "All", "note": "OK", "status": "Passed", "severity": "ok"}]
    return {"score": score, "grade": grade, "summary": summary, "stats": stats, "issues": issues}


@router.get("/{document_id}/integrity", dependencies=[Depends(current_principal)])
def get_document_integrity(document_id: str, session: Session = Depends(db)) -> dict:
    """Real pre-flight integrity for one uploaded document (drives the Document Integrity
    screen when working a real file, rather than the demo project)."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _serialize_document_integrity(row)


def _latest_run(session: Session, document_id: str):
    """Most recent extraction run for a document, or None if it hasn't been extracted."""
    from app.db.models import ExtractionRun

    return session.execute(
        select(ExtractionRun)
        .where(ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.created_at.desc())
    ).scalars().first()


def _prov_label(prov: dict | None) -> str:
    if not prov:
        return "—"
    if prov.get("source_kind") == "spreadsheet" and prov.get("sheet"):
        return f"{prov['sheet']}!{prov.get('cell', '')}"
    return f"p.{(prov.get('page_index', 0) or 0) + 1}"


_LOW_CONF = 0.75  # mapping confidence below this routes to review


def _build_review(rows: list[dict], filename: str) -> dict:
    """Derive the human-in-the-loop review queue from a real extraction: unmapped and
    low-confidence line items become review checks (the QA the analyst works before
    export). No demo data involved."""
    checks: list[dict] = []
    unmapped = low_conf = 0
    for i, r in enumerate(rows):
        key = r.get("canonical_key")
        conf = r.get("mapping_confidence")
        flags = r.get("flags") or []
        first = (r.get("values") or [{}])[0]
        val = first.get("value")
        where = f"{filename} · {_prov_label(first.get('provenance'))}"
        pct = f"{round(conf * 100)}%" if isinstance(conf, (int, float)) else "—"

        if not key:
            unmapped += 1
            checks.append({
                "id": f"chk-unmapped-{i}", "type": "unmapped", "icon": "?",
                "title": r.get("source_label", "Line item"), "where": where,
                "severity": "Unmapped", "tone": "low", "delta": "—",
                "target": r.get("source_label", ""),
                "calc": [
                    ["Source label", r.get("source_label", ""), False],
                    ["Mapped to", "— (no confident match)", True],
                    ["Value", str(val) if val is not None else "—", False],
                ],
                "fix": "No canonical concept matched with confidence. Pick the correct template "
                       "line item, or add an alias so future runs map it automatically.",
            })
        elif "low_mapping_confidence" in flags or (isinstance(conf, (int, float)) and conf < _LOW_CONF):
            low_conf += 1
            checks.append({
                "id": f"chk-lowconf-{i}", "type": "low_confidence", "icon": "!",
                "title": r.get("source_label", "Line item"), "where": where,
                "severity": "Low confidence", "tone": "med", "delta": pct,
                "target": r.get("source_label", ""),
                "calc": [
                    ["Source label", r.get("source_label", ""), False],
                    ["Mapped to", key, True],
                    ["Method", r.get("mapping_method") or "—", False],
                    ["Confidence", pct, False],
                    ["Value", str(val) if val is not None else "—", False],
                ],
                "fix": "The mapping is uncertain. Confirm the concept is correct or reassign it; "
                       "the value and its source location are shown so you can verify against the document.",
            })
    total = len(checks)
    passed = max(0, len(rows) - total)
    return {
        "checks": checks,
        "tabs": [
            {"label": "All", "count": total},
            {"label": "Unmapped", "count": unmapped},
            {"label": "Low confidence", "count": low_conf},
        ],
        "summary": {"open": total, "passed": passed},
    }


@router.get("/{document_id}/run", dependencies=[Depends(current_principal)])
def get_document_run(document_id: str, session: Session = Depends(db)) -> dict:
    """The latest extraction result for a document (drives the Export preview/counts for a
    real run). 404 until the document has been extracted."""
    from app.db.models import Document

    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    return {"run_id": run.id, "status": run.status, "result": run.result}


@router.get("/{document_id}/review", dependencies=[Depends(current_principal)])
def get_document_review(document_id: str, session: Session = Depends(db)) -> dict:
    """Real review queue for a document, derived from its latest extraction."""
    from app.db.models import Document

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        return {"checks": [], "tabs": [{"label": "All", "count": 0}], "summary": {"open": 0, "passed": 0}}
    return _build_review(run.result.get("rows", []), doc.filename or "document")


@router.get("/{document_id}/export", dependencies=[Depends(require(Permission.EXPORT_RUN))])
def export_document(
    document_id: str,
    fmt: str = Query("excel", pattern="^(excel|json)$"),
    session: Session = Depends(db),
) -> Response:
    """Export a real document's extracted, mapped line items as Excel or JSON, built from
    the latest run (not the demo project)."""
    from app.db.models import Document
    from app.services.export import build_rows_json, build_rows_xlsx

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    run = _latest_run(session, document_id)
    if run is None or not run.result:
        raise HTTPException(status_code=404, detail="No extraction run yet for this document")
    rows = run.result.get("rows", [])
    name = (doc.filename or "extract").rsplit(".", 1)[0]
    if fmt == "json":
        data = build_rows_json(rows, filename=doc.filename or "document")
        return Response(content=data, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    data = build_rows_xlsx(rows, filename=doc.filename or "document")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
    )


@router.get("/{document_id}")
def get_document(document_id: str, session: Session = Depends(db)) -> dict:
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": row.id,
        "filename": row.filename,
        "status": row.status,
        "format": row.fmt,
        "locale": row.locale,
        "page_count": row.page_count,
        "integrity_report": row.integrity_report,
    }


@router.get("/{document_id}/pages/{page_index}/image", dependencies=[Depends(current_principal)])
def get_page_image(
    document_id: str,
    page_index: int,
    dpi: int = Query(110, ge=50, le=300),
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> Response:
    """Rasterize one PDF page to PNG — the backdrop the frontend draws the value's
    normalized bbox over (click-to-source). PDF only; spreadsheets have no page image."""
    from app.db.models import Document

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if row.fmt != "pdf":
        raise HTTPException(status_code=400, detail="Page images are only available for PDFs")
    try:
        import fitz
    except ImportError:  # pragma: no cover - PyMuPDF is a core dep
        raise HTTPException(status_code=501, detail="PDF rendering unavailable")
    data = store.get(row.object_key)
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
        if page_index < 0 or page_index >= pdf.page_count:
            raise HTTPException(status_code=404, detail="Page out of range")
        png = pdf[page_index].get_pixmap(dpi=dpi).tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not render page: {exc}")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300"})


@router.get("/{document_id}/cell-context", dependencies=[Depends(current_principal)])
def get_cell_context(
    document_id: str,
    sheet: str = Query(..., description="Sheet name the value came from"),
    cell: str = Query(..., description="Cell reference, e.g. C14"),
    radius: int = Query(4, ge=1, le=12),
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
) -> dict:
    """A window of cells around a value's origin — the spreadsheet click-to-source
    backdrop (mirrors the PDF page image for XLSX sources)."""
    from app.db.models import Document
    from app.services.excel_extract import cell_context

    row = session.get(Document, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if row.fmt != "xlsx":
        raise HTTPException(status_code=400, detail="Cell context is only available for spreadsheets")
    data = store.get(row.object_key)
    try:
        return cell_context(data, sheet=sheet, cell=cell, radius=radius)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Sheet not found: {sheet}")

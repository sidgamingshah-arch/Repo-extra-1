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

"""Extraction endpoints: start a run (thin) and fetch status.

Runs the pipeline synchronously against the stored document for this foundation. The
WebSocket progress stream is stubbed with the contract shape; the background-worker
swap does not change these routes.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from pathlib import Path

from app.api.deps import db, settings as get_settings_dep
from app.api.routes.documents import authorized_document
from app.config import Settings
from app.ports.object_store import LocalObjectStore
from app.schemas.loader import load_ontology
from app.security import Permission, require
from app.services import audit as audit_svc
from app.services.documents import run_extraction

router = APIRouter(tags=["extractions"])


def _serialize_rows(doc_model) -> list[dict]:
    """Extracted line items in a view-friendly shape, each value with its provenance
    (sheet+cell for Excel, page+bbox for PDF) so the UI can show click-to-source."""
    rows = []
    for li in doc_model.line_items:
        values = []
        for ev in li.values.values():
            p = ev.provenance
            prov = None
            if p is not None:
                prov = {
                    "source_kind": p.source_kind,
                    "page_index": p.page_index,
                    "sheet": p.sheet, "cell": p.cell, "label_cell": p.label_cell,
                    "bbox": (p.bbox.model_dump() if p.bbox is not None else None),
                    "text_snippet": p.text_snippet,
                }
            values.append({
                "period_label": ev.period_label,
                "basis": ev.basis.value,
                "value": (str(ev.value) if ev.value is not None else None),
                "provenance": prov,
            })
        rows.append({
            "source_label": li.source_label,
            "canonical_key": li.canonical_key,
            "note": li.note_number,
            "role": li.role.value,
            "mapping_method": li.confidence.method,
            "mapping_confidence": li.confidence.mapping,
            "flags": list(li.confidence.flags),
            "values": values,
        })
    return rows


def _prov_dict(p):
    if p is None:
        return None
    return {
        "source_kind": p.source_kind, "page_index": p.page_index,
        "sheet": p.sheet, "cell": p.cell, "label_cell": p.label_cell,
        "bbox": (p.bbox.model_dump() if p.bbox is not None else None),
        "text_snippet": p.text_snippet,
    }


def _serialize_notes(doc_model) -> list[dict]:
    """Extracted note detail tables → view/export shape: each note with its own breakdown
    rows (label + period values) and provenance."""
    notes = []
    for nt in doc_model.notes:
        rows = []
        for it in nt.items:
            values = [{
                "period_label": ev.period_label, "basis": ev.basis.value,
                "value": (str(ev.value) if ev.value is not None else None),
                "provenance": _prov_dict(ev.provenance),
            } for ev in it.values.values()]
            rows.append({"label": it.raw_label, "values": values})
        page = (nt.source_pages[0] if nt.source_pages else 0)
        notes.append({"no": nt.note_number, "title": nt.title, "page": page + 1, "rows": rows})
    return notes


class ExtractionOptions(BaseModel):
    template_version_id: str | None = None
    ontology_version_id: str | None = None
    basis: list[str] = []
    target_currency: str | None = None
    target_units: int | None = None
    # Whether the user asked to review/adjust detected page scope before
    # extraction. Defaults to auto (False): detect pages and extract in one pass.
    confirm_scope: bool = False
    # Entity name used to mint the run id (entity-slug + timestamp). Falls back to the
    # document filename when omitted.
    entity: str | None = None


def _run_extraction_task(run_id: str, object_key: str, filename: str, options: dict,
                         entity: str, provider: str, model_fallback: str) -> None:
    """Run the pipeline off the request thread and record the outcome on the run row. Opens
    its own DB session + object store (the request's are gone by the time this executes)."""
    from app.config import get_settings
    from app.db.base import SessionLocal
    from app.db.models import ExtractionRun, OntologyVersion

    session = SessionLocal()
    try:
        settings = get_settings()
        store = LocalObjectStore(settings.object_store_root)
        ontology = None
        oid = options.get("ontology_version_id")
        if oid:
            ont_row = session.get(OntologyVersion, oid)
            if ont_row is not None:
                ontology = load_ontology(ont_row.definition)

        data = store.get(object_key)
        doc_model, ctx = run_extraction(data, filename=filename, ontology=ontology)
        run = session.get(ExtractionRun, run_id)
        if run is None:
            return

        # Presence scan for qualitative disclosures (auditor qualification, contingent
        # liabilities, guarantees, …) over the document text — stored on the run.
        from app.services.derived import document_text, scan_disclosures
        try:
            disclosures = scan_disclosures(document_text(data, doc_model.fmt.value))
        except Exception:  # noqa: BLE001 — a scan failure must not fail the extraction
            disclosures = []

        recon = doc_model.reconciliation
        run.result = {
            "locale": doc_model.locale,
            "format": doc_model.fmt.value,
            "filename": filename,
            "pages": [p.model_dump(mode="json") for p in doc_model.pages],
            "line_item_count": len(doc_model.line_items),
            "notes": len(doc_model.notes),
            "rows": _serialize_rows(doc_model),
            "note_details": _serialize_notes(doc_model),
            "disclosures": disclosures,
            "reconciliation": ([e.model_dump(mode="json") for e in recon.entries] if recon else []),
        }
        run.status = "succeeded"
        run.progress = {"phase": "done", "pct": 1.0}
        run.logs = "\n".join(ctx.logs)
        session.commit()

        used_llm = ctx.llm_calls > 0
        audit_svc.record(run.document_id, audit_svc.AuditEntry(
            run_id=run_id, entity=entity, action="extraction",
            provider=provider, model=ctx.llm_model or model_fallback,
            input_tokens=ctx.llm_input_tokens if used_llm else None,
            output_tokens=ctx.llm_output_tokens if used_llm else None,
            status="succeeded",
        ))
    except Exception as exc:  # noqa: BLE001 — record failure on the run, don't crash the worker
        run = session.get(ExtractionRun, run_id)
        if run is not None:
            run.status = "failed"
            run.progress = {"phase": "failed", "pct": 1.0}
            run.logs = f"{type(exc).__name__}: {exc}"
            session.commit()
        audit_svc.record(run.document_id if run else "unknown", audit_svc.AuditEntry(
            run_id=run_id, entity=entity, action="extraction",
            provider=provider, model=model_fallback,
            input_tokens=None, output_tokens=None, status="failed",
        ))
    finally:
        session.close()


@router.post("/documents/{document_id}/extractions", status_code=202,
             dependencies=[Depends(require(Permission.PIPELINE_RUN)), Depends(authorized_document)])
def start_extraction(
    document_id: str,
    body: ExtractionOptions,
    background: BackgroundTasks,
    session: Session = Depends(db),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    """Kick off extraction as a background job. Returns 202 immediately with a 'running'
    run; the frontend polls GET /extractions/{run_id} (or /documents/{id}/run) until it
    reaches 'succeeded'/'failed'. Keeps the API responsive on large files without a
    separate worker/broker."""
    from app.db.models import Document, ExtractionRun

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    entity = body.entity or Path(doc.filename or "").stem or "document"
    run_id = audit_svc.make_run_id(entity)
    run = ExtractionRun(
        id=run_id, document_id=doc.id,
        template_version_id=body.template_version_id,
        ontology_version_id=body.ontology_version_id,
        status="running", options=body.model_dump(),
        progress={"phase": "queued", "pct": 0.0}, result=None,
    )
    session.add(run)
    session.commit()

    background.add_task(_run_extraction_task, run_id, doc.object_key, doc.filename or "",
                        body.model_dump(), entity, settings.llm.provider, settings.llm.model)
    return {"run_id": run_id, "status": "running",
            "stream_url": f"/api/v1/extractions/{run_id}/stream"}


@router.get("/extractions/{run_id}")
def get_run(run_id: str, session: Session = Depends(db)) -> dict:
    from app.db.models import ExtractionRun

    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run.id, "status": run.status, "progress": run.progress,
            "result": run.result}

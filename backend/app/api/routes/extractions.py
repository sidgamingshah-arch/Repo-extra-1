"""Extraction endpoints: start a run (thin) and fetch status.

Runs the pipeline synchronously against the stored document for this foundation. The
WebSocket progress stream is stubbed with the contract shape; the background-worker
swap does not change these routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from pathlib import Path

from app.api.deps import db, object_store, settings as get_settings_dep
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


@router.post("/documents/{document_id}/extractions", status_code=202,
             dependencies=[Depends(require(Permission.PIPELINE_RUN))])
def start_extraction(
    document_id: str,
    body: ExtractionOptions,
    session: Session = Depends(db),
    store: LocalObjectStore = Depends(object_store),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    from app.db.models import Document, ExtractionRun, OntologyVersion

    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    ontology = None
    if body.ontology_version_id:
        ont_row = session.get(OntologyVersion, body.ontology_version_id)
        if ont_row is not None:
            ontology = load_ontology(ont_row.definition)

    data = store.get(doc.object_key)
    doc_model, ctx = run_extraction(data, filename=doc.filename, ontology=ontology)

    entity = body.entity or Path(doc.filename or "").stem or "document"
    run_id = audit_svc.make_run_id(entity)
    rows = _serialize_rows(doc_model)

    run = ExtractionRun(
        id=run_id,
        document_id=doc.id,
        template_version_id=body.template_version_id,
        ontology_version_id=body.ontology_version_id,
        status="succeeded",
        options=body.model_dump(),
        progress={"phase": "done", "pct": 1.0},
        result={
            "locale": doc_model.locale,
            "format": doc_model.fmt.value,
            "filename": doc.filename,
            "pages": [p.model_dump(mode="json") for p in doc_model.pages],
            "line_item_count": len(doc_model.line_items),
            "notes": len(doc_model.notes),
            "rows": rows,
        },
        logs="\n".join(ctx.logs),
    )
    session.add(run)
    session.commit()

    # Audit trail entry for the run. Description-based mapping (services.mapping) uses the
    # LLM, so record the real input/output token usage accumulated on the context when the
    # LLM was engaged; otherwise leave them null (shown as "—" in the audit log).
    used_llm = ctx.llm_calls > 0
    audit_svc.record(doc.id, audit_svc.AuditEntry(
        run_id=run_id, entity=entity, action="extraction",
        provider=settings.llm.provider, model=ctx.llm_model or settings.llm.model,
        input_tokens=ctx.llm_input_tokens if used_llm else None,
        output_tokens=ctx.llm_output_tokens if used_llm else None,
        status="succeeded",
    ))

    return {"run_id": run.id, "status": run.status, "result": run.result,
            "stream_url": f"/api/v1/extractions/{run.id}/stream"}


@router.get("/extractions/{run_id}")
def get_run(run_id: str, session: Session = Depends(db)) -> dict:
    from app.db.models import ExtractionRun

    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run.id, "status": run.status, "progress": run.progress,
            "result": run.result}

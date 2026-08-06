"""Extraction endpoints: start a run (thin) and fetch status.

Runs the pipeline synchronously against the stored document for this foundation. The
WebSocket progress stream is stubbed with the contract shape; the background-worker
swap does not change these routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import db, object_store, settings as get_settings_dep
from app.config import Settings
from app.ports.object_store import LocalObjectStore
from app.schemas.loader import load_ontology
from app.services.documents import run_extraction

router = APIRouter(tags=["extractions"])


class ExtractionOptions(BaseModel):
    template_version_id: str | None = None
    ontology_version_id: str | None = None
    basis: list[str] = []
    target_currency: str | None = None
    target_units: int | None = None
    # Whether the user asked to review/adjust detected page scope before
    # extraction. Defaults to auto (False): detect pages and extract in one pass.
    confirm_scope: bool = False


@router.post("/documents/{document_id}/extractions", status_code=202)
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

    run = ExtractionRun(
        document_id=doc.id,
        template_version_id=body.template_version_id,
        ontology_version_id=body.ontology_version_id,
        status="succeeded",
        options=body.model_dump(),
        progress={"phase": "done", "pct": 1.0},
        result={
            "locale": doc_model.locale,
            "format": doc_model.fmt.value,
            "pages": [p.model_dump(mode="json") for p in doc_model.pages],
            "line_items": len(doc_model.line_items),
            "notes": len(doc_model.notes),
        },
        logs="\n".join(ctx.logs),
    )
    session.add(run)
    session.commit()
    return {"run_id": run.id, "status": run.status,
            "stream_url": f"/api/v1/extractions/{run.id}/stream"}


@router.get("/extractions/{run_id}")
def get_run(run_id: str, session: Session = Depends(db)) -> dict:
    from app.db.models import ExtractionRun

    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run.id, "status": run.status, "progress": run.progress,
            "result": run.result}

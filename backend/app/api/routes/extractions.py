"""Extraction endpoints: start a run and fetch its status.

``POST /documents/{id}/extractions`` returns 202 immediately and runs the pipeline in a FastAPI
BackgroundTask; progress and results are read by polling ``GET /extractions/{run_id}`` (the
frontend polls once a second while the run is ``running`` — see ``lib/queries.ts``).

There is no WebSocket stream. The earlier "stubbed WS contract" note in this docstring described
something that was never built, and the run has not been synchronous since extraction moved to the
background task.
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
from app.schemas.loader import load_ontology, load_template
from app.security import Permission, require
from app.services import audit as audit_svc
from app.services.documents import run_extraction

router = APIRouter(tags=["extractions"])


def _maybe_cache_credit_narrative(session: Session, run, locale: str, entity: str | None) -> None:
    """Auto-generate the LLM credit narrative once and cache it on the run, so the Analysis
    screen / export show it without a manual click. Best-effort and fully guarded: it runs only
    when a real LLM provider is configured, and any failure (no key, unreachable, thin data)
    leaves the deterministic credit view untouched — the extraction has already succeeded."""
    try:
        from app.config import get_settings

        settings = get_settings()
        if settings.llm.provider == "stub":
            return
        from app.ports.registry import registry as reg
        from app.services.analysis_llm import run_credit_narrative
        from app.services.derived import build_credit_analysis, localize_disclosures

        rows = run.result.get("rows", [])
        disclosures = localize_disclosures(run.result.get("disclosures", []), locale)
        credit = build_credit_analysis(rows, disclosures, locale=locale)
        if not credit.get("factors") and not credit.get("flags"):
            return
        provider = reg.get("llm", settings.llm.provider)
        result, meta = run_credit_narrative(provider, credit, entity=entity or "",
                                            locale=locale, max_tokens=settings.llm.max_tokens)
        run.result = {**run.result, "credit_narrative": {
            "text": result.narrative, "provider": settings.llm.provider,
            "model": meta.get("model", settings.llm.model)}}
        session.commit()
    except Exception:  # noqa: BLE001 — optional enrichment; never disturb a succeeded run
        session.rollback()


def _maybe_cache_netting(session: Session, run, locale: str) -> None:
    """Evaluate the ontology's generic containment-netting policies against THIS extraction once,
    via the LLM, and cache the confirmed (resolved) rules on the run. The statement/export then
    apply the deterministic math from the cached decision — so a policy nets only where the model
    confirmed the containment, and per-request rendering stays fast. Best-effort and guarded."""
    try:
        from app.config import get_settings

        settings = get_settings()
        if settings.llm.provider == "stub":
            return
        from app.api.routes.documents import _netting_rules_for_run
        rules = _netting_rules_for_run(session, run)
        if not rules:
            return
        from app.ports.registry import registry as reg
        from app.services.netting import resolve_netting

        provider = reg.get("llm", settings.llm.provider)
        resolved = resolve_netting(provider, run.result.get("rows", []), rules,
                                   max_tokens=settings.llm.max_tokens)
        run.result = {**run.result, "netting": resolved}
        session.commit()
    except Exception:  # noqa: BLE001 — optional; a succeeded extraction is never disturbed
        session.rollback()


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
                prov = _prov_dict(p)
            cv = ev.confidence
            values.append({
                "period_label": ev.period_label,
                "period_display": ev.period_display,  # real period-end date for headers, if any
                "basis": ev.basis.value,
                "value": (str(ev.value) if ev.value is not None else None),
                "provenance": prov,
                # Per-value confidence vector — the weakest signal and any flags let the UI
                # colour and explain each number, not just the row.
                "confidence": {
                    "mapping": cv.mapping, "validation": cv.validation,
                    "overall": cv.overall, "weakest": cv.weakest,
                    "flags": list(cv.flags),
                },
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
    """One provenance record as the API serves it — ONE spelling, used by the face rows and the
    note rows alike (the face path used to carry an inline copy of this dict, and the two then
    disagreed about which fields exist).

    ``label_bbox`` is carried because the row LABEL's geometry is the only box on a paginated source
    that does not move when the figure does. ``bbox`` is the value word's box (row_reconstruct.py),
    so "Cash and cash equivalents 1,204" and the same line printed 12,048 have different ``bbox``
    x0s — right-aligned figures grow leftwards. The review queue's judgement subject is anchored on
    this geometry (api/routes/documents.py::_prov_anchor), and an anchor that moves with the figure
    means a reviewer's acceptance is reported as belonging to a finding that was corrected when the
    figure merely changed. The label box is what makes the anchor value-independent, and it never
    reached the anchor before because this serializer dropped it.
    """
    if p is None:
        return None
    return {
        "source_kind": p.source_kind, "page_index": p.page_index,
        "sheet": p.sheet, "cell": p.cell, "label_cell": p.label_cell,
        "bbox": (p.bbox.model_dump() if p.bbox is not None else None),
        "label_bbox": (p.label_bbox.model_dump() if p.label_bbox is not None else None),
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
                "period_label": ev.period_label,
                # The printed column header ("31 December 2024"), carried the same way the face
                # serializer carries it above. Without it a note table's own column dates were
                # dropped on the way to the API, so the Notes screen could only ever fall back to
                # Current/Prior even for Excel and date-banded PDFs.
                "period_display": ev.period_display,
                "basis": ev.basis.value,
                "value": (str(ev.value) if ev.value is not None else None),
                "provenance": _prov_dict(ev.provenance),
            } for ev in it.values.values()]
            # Carry the row's role (line/subtotal/total) and mapping confidence so the notes
            # detail renders subtotal/total emphasis and a per-row confidence badge.
            rows.append({"label": it.raw_label, "role": it.role.value,
                         "confidence": it.confidence.overall, "values": values})
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


def _in_force_for_template(session: Session, template_key: str):
    """The rulebook in force for a template — the extractor's own choice, never a second copy
    of that rule (see ``services.ontology_select``)."""
    from app.services.ontology_select import select_for_template

    return select_for_template(session, template_key) if template_key else None


def rulebook_record(session: Session, ontology_version_id: str | None) -> dict:
    """WHICH rulebook this run reads the filing against, decided once, when the run starts.

    Recorded on the run because the alternative — a reader re-deriving it later — is what made
    reloading the extraction view an audit failure: the client asked for the rulebook IT thought
    was in force, ran the filing against a superseded one, and labelled the result as the rulebook
    in force. Which rulebook produced a figure is part of the figure. A run states it, and every
    view reports the stated value instead of guessing again.

    ``status`` is the whole claim in one word: ``in_force`` (this WAS the rulebook in force for its
    template when the run started), ``superseded`` (a stored rulebook declares it replaced — a
    legitimate thing to pin, never a thing to call current), ``pinned`` (live, but not the one in
    force), ``engine_default`` (the run named no rulebook, so it maps against none and its pages
    are read by the shipped default) or ``missing`` (the id named no stored rulebook).
    """
    from app.db.models import OntologyVersion
    from app.services.ontology_select import rulebooks_for_template, superseded_keys

    record = {
        "ontology_version_id": ontology_version_id or "",
        "ontology_key": "", "version": 0, "target_template_key": "",
        "status": "engine_default" if not ontology_version_id else "missing",
        "in_force": False,
        "in_force_ontology_key": "", "in_force_version": 0,
    }
    if not ontology_version_id:
        return record
    row = session.get(OntologyVersion, ontology_version_id)
    if row is None:
        return record

    siblings = rulebooks_for_template(session, row.target_template_key)
    superseded = row.ontology_key in superseded_keys(siblings)
    chosen = _in_force_for_template(session, row.target_template_key)
    # A superseded rulebook is never "in force", even when it is the best answer the selector can
    # give: with every stored rulebook for a template superseded, ``select_for_template`` falls
    # back to the whole list and returns one of them, and calling that in force would tell a
    # reviewer a figure came from the current rulebook when it came from a replaced one.
    in_force = chosen is not None and chosen.id == row.id and not superseded
    record.update({
        "ontology_key": row.ontology_key, "version": row.version,
        "target_template_key": row.target_template_key,
        "status": "superseded" if superseded else ("in_force" if in_force else "pinned"),
        "in_force": in_force,
        "in_force_ontology_key": chosen.ontology_key if chosen is not None else "",
        "in_force_version": chosen.version if chosen is not None else 0,
    })
    return record


def _run_extraction_task(run_id: str, object_key: str, filename: str, options: dict,
                         entity: str, provider: str, model_fallback: str,
                         included_pages: list[int] | None = None) -> None:
    """Run the pipeline off the request thread and record the outcome on the run row. Opens
    its own DB session + object store (the request's are gone by the time this executes)."""
    from app.config import get_settings
    from app.db.base import SessionLocal
    from app.db.models import ExtractionRun, OntologyVersion, TemplateVersion

    session = SessionLocal()
    try:
        settings = get_settings()
        store = LocalObjectStore(settings.object_store_root)
        ontology = None
        oid = options.get("ontology_version_id")
        if oid:
            ont_row = session.get(OntologyVersion, oid)
            if ont_row is not None:
                # RESOLVED, because this is the one call site whose result actually maps a filing.
                # A v2 rulebook declares statement / section_scope / temporality / face_only ONLY on
                # its section_defaults entries — zero concepts carry them — so loading it
                # unresolved gives every concept those fields as None and the whole section layer
                # is absent rather than degraded. A v1 definition has no section layer to fold and
                # comes back untouched, so this is safe for both.
                ontology = load_ontology(ont_row.definition, resolve=True)
        # The template is the run's target definition; the structural stage validates the
        # extraction against the rollups and identities it declares.
        template = None
        tid = options.get("template_version_id")
        if tid:
            tpl_row = session.get(TemplateVersion, tid)
            if tpl_row is not None:
                try:
                    template = load_template(tpl_row.definition)
                except Exception:  # noqa: BLE001 — a bad stored template must not fail the run
                    template = None

        data = store.get(object_key)
        doc_model, ctx = run_extraction(data, filename=filename, ontology=ontology,
                                        included_pages=included_pages, template=template)
        run = session.get(ExtractionRun, run_id)
        if run is None:
            return

        # Presence scan for qualitative disclosures (auditor qualification, contingent
        # liabilities, guarantees, …) over the document text — stored on the run. The same
        # page text yields the entity name shown at the top of the extraction/statement.
        from app.services.derived import detect_entity_name, document_text, scan_disclosures
        entity_name = None
        try:
            pages_text = document_text(data, doc_model.fmt.value)
            disclosures = scan_disclosures(pages_text)
            entity_name = detect_entity_name(pages_text)
        except Exception:  # noqa: BLE001 — a scan failure must not fail the extraction
            disclosures = []

        recon = doc_model.reconciliation
        structural = doc_model.structural
        # The rulebook decision recorded when the run was created, carried onto the result with
        # whether that rulebook actually LOADED. A pinned rulebook whose stored definition will not
        # load governs nothing, and a result that claimed it did would be the same lie in a
        # different place.
        rulebook = dict((run.options or {}).get("rulebook") or {})
        if not rulebook:
            # A run created outside the route (a re-run script, a seed) still has to say which
            # rulebook produced its figures, so the record is made here rather than left blank.
            rulebook = rulebook_record(session, oid)
        rulebook["applied"] = ontology is not None
        run.result = {
            "locale": doc_model.locale,
            # Which rulebook produced these figures — stated by the run, never re-derived by a
            # reader (see :func:`rulebook_record`).
            "rulebook": rulebook,
            "format": doc_model.fmt.value,
            "filename": filename,
            "entity": entity_name,
            "pages": [p.model_dump(mode="json") for p in doc_model.pages],
            "page_count": len(doc_model.pages),
            "line_item_count": len(doc_model.line_items),
            "notes": len(doc_model.notes),
            "rows": _serialize_rows(doc_model),
            "note_details": _serialize_notes(doc_model),
            "disclosures": disclosures,
            "reconciliation": ([e.model_dump(mode="json") for e in recon.entries] if recon else []),
            # Template-structure validation: relations checked (pass/fail) AND the ones that
            # could not be checked, so partial coverage is visible rather than implied.
            "structural": ([r.model_dump(mode="json") for r in structural.results]
                           if structural else []),
            # Leftover lines a model placed in a section's Others to reconcile a printed subtotal
            # with its components — kept so the routing is inspectable, not silent.
            "gap_routings": list(doc_model.gap_routings or []),
            "units": (doc_model.unit_context.model_dump(mode="json")
                      if doc_model.unit_context else None),
            # How mapping ran. Surfaced (not just logged) so a deterministic-only run — the
            # fallback when no LLM is configured — is visibly weaker rather than silently so.
            "mapping": {
                "strategy": ctx.mapping_strategy or "deterministic",
                "reason": ctx.mapping_strategy_reason,
                "llm_calls": ctx.llm_calls,
                "model": ctx.llm_model or "",
            },
        }
        run.status = "succeeded"
        run.progress = {"phase": "done", "pct": 1.0}
        run.logs = "\n".join(ctx.logs)
        session.commit()

        _maybe_cache_credit_narrative(session, run, doc_model.locale or "en", entity_name)
        _maybe_cache_netting(session, run, doc_model.locale or "en")

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

    # Enforce the integrity gate at the API boundary: a document with BLOCKER findings
    # (corrupt / encrypted / unreadable) cannot be extracted — refuse rather than return a
    # misleading "succeeded" empty run.
    report = doc.integrity_report or {}
    blockers = [f for f in report.get("findings", []) if f.get("severity") == "blocker"]
    if blockers:
        raise HTTPException(status_code=422, detail={
            "error": "integrity_blocked",
            "message": "This document did not pass the integrity check and cannot be extracted.",
            "blockers": [f.get("message") for f in blockers],
        })

    entity = body.entity or Path(doc.filename or "").stem or "document"
    run_id = audit_svc.make_run_id(entity)
    # Settle which rulebook this run reads the filing against BEFORE it starts, and keep it on the
    # run. The caller may legitimately pin a superseded rulebook (reproducing an earlier spread),
    # and the run says so rather than letting the screen decide afterwards what it must have used.
    rulebook = rulebook_record(session, body.ontology_version_id)
    run = ExtractionRun(
        id=run_id, document_id=doc.id,
        template_version_id=body.template_version_id,
        ontology_version_id=body.ontology_version_id,
        status="running", options={**body.model_dump(), "rulebook": rulebook},
        progress={"phase": "queued", "pct": 0.0}, result=None,
    )
    session.add(run)
    session.commit()

    background.add_task(_run_extraction_task, run_id, doc.object_key, doc.filename or "",
                        body.model_dump(), entity, settings.llm.provider, settings.llm.model,
                        doc.page_scope)
    # The URL of the mechanism that ACTUALLY reports progress — the endpoint the client polls.
    # This field used to name `/extractions/{run_id}/stream`, a WebSocket route that exists
    # nowhere in this codebase: a GET on it 404s, no client ever read it, and the docs correction
    # that removed the same claim from the prose left it standing here in machine-readable form.
    # Pointing it at GET /extractions/{run_id} rather than deleting it keeps the response
    # self-describing for a caller that has only the response to go on, and there is now a test
    # holding this URL to being the one the API serves.
    return {"run_id": run_id, "status": "running", "rulebook": rulebook,
            "progress_url": f"/api/v1/extractions/{run_id}"}


@router.get("/extractions/{run_id}")
def get_run(run_id: str, session: Session = Depends(db)) -> dict:
    from app.db.models import ExtractionRun

    run = session.get(ExtractionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    # The recorded rulebook rides alongside the result so the view can name it from the FIRST poll
    # — while the run is still running, and even if it fails — instead of computing a candidate of
    # its own and labelling the run with that.
    return {"run_id": run.id, "status": run.status, "progress": run.progress,
            "rulebook": (run.options or {}).get("rulebook"),
            "result": run.result}

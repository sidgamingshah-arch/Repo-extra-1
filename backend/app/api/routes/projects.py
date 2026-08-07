"""Seeded demo-project endpoints — the data the workspace/review/notes/export views
render. Uploaded documents use the real pipeline (documents/extractions routers);
this router serves the reviewed Ind-AS sample project end-to-end.
"""
from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.config import get_settings
from app.sample.demo import CONF_PCT, DEMO, localize_label
from app.sample.i18n_data import tr
from app.security import Permission, current_principal, require
from app.services import checks as checks_engine
from app.services.export import build_json, build_xlsx

# Every project endpoint requires an authenticated caller (session token, or the
# X-Role dev header when enabled). Per-action permissions are enforced with require().
router = APIRouter(prefix="/projects", tags=["projects"],
                   dependencies=[Depends(current_principal)])

# In-memory edit overrides: {line_item_id: {"value": int, "formula": str}}.
_OVERRIDES: dict[str, dict] = {}

_STD_SCALE = 0.88
_VIEWER = {
    "balance_sheet": {
        "company": "RELIANCE INDUSTRIES LIMITED",
        "subtitle": "Consolidated Balance Sheet as at 31 March 2025",
        "chips": [{"label": "BS · p.142", "active": True}, {"label": "Note 12 · p.171", "active": False}],
        "callout": "↳ Linked to Note 12 — Trade receivables (p.171). Face value shown net of ₹12,400 cr related-party receivables reclassified under Note 12.3.",
    },
    "profit_and_loss": {
        "company": "RELIANCE INDUSTRIES LIMITED",
        "subtitle": "Consolidated Statement of Profit and Loss for the year ended 31 March 2025",
        "chips": [{"label": "P&L · p.145", "active": True}, {"label": "Note 25 · p.184", "active": False}],
        "callout": "↳ Finance costs (Note 25) flagged: extracted as a credit; ontology expects an expense (negative).",
    },
    "cash_flow": {
        "company": "RELIANCE INDUSTRIES LIMITED",
        "subtitle": "Consolidated Statement of Cash Flows for the year ended 31 March 2025",
        "chips": [{"label": "CF · p.149", "active": True}, {"label": "Note 13 · p.172", "active": False}],
        "callout": "↳ Closing cash ties to Note 13 (Cash & bank balances) and the face of the Balance Sheet.",
    },
}


@router.get("/{project_id}")
def get_project(project_id: str) -> dict:
    if project_id != "demo":
        raise HTTPException(404, "Unknown project")
    return {"project": DEMO["project"], "documents": DEMO["documents"]}


@router.get("/{project_id}/integrity")
def get_integrity(project_id: str, locale: str = Query("en")) -> dict:
    data = deepcopy(DEMO["integrity"])
    if locale != "en":
        data["grade"] = tr(data["grade"], locale)
        data["summary"] = tr(data["summary"], locale)
        for s in data["stats"]:
            s["label"] = tr(s["label"], locale)
            s["sub"] = tr(s["sub"], locale)
        for i in data["issues"]:
            i["title"] = tr(i["title"], locale)
            i["detail"] = tr(i["detail"], locale)
            i["note"] = tr(i["note"], locale)
            i["status"] = tr(i["status"], locale)
    return data


@router.get("/{project_id}/pages")
def get_pages(project_id: str, locale: str = Query("en")) -> dict:
    pages = deepcopy(DEMO["pages"])
    filters = deepcopy(DEMO["page_filters"])
    if locale != "en":
        for p in pages:
            p["cls"] = tr(p["cls"], locale)
            p["sub"] = tr(p["sub"], locale)
        for f in filters:
            f["label"] = tr(f["label"], locale)
    return {"pages": pages, "filters": filters, "focused": 14, "total": 84, "skipped": 70}


def _scale(v, basis: str):
    if v is None:
        return None
    return v if basis == "consolidated" else round(v * _STD_SCALE)


@router.get("/{project_id}/statements/{statement}")
def get_statement(project_id: str, statement: str,
                  basis: str = Query("consolidated"),
                  locale: str = Query("en")) -> dict:
    st = DEMO["statements"].get(statement)
    if st is None:
        raise HTTPException(404, f"Unknown statement {statement!r}")
    proj = DEMO["project"]
    rows = []
    for r in st["rows"]:
        kind = r.get("kind", "item")
        # label = localized output; source_label = original (English) for the source view
        row = {"id": r["id"], "label": localize_label(r["label"], locale),
               "source_label": r["label"], "kind": kind}
        if kind == "item":
            row["level"] = 1
            row["note"] = r.get("note")
            row["note2"] = r.get("note2", r.get("note"))
            row["status"] = r.get("status")
            if r.get("conf"):
                row["confidence"] = {"cat": r["conf"], "pct": CONF_PCT[r["conf"]]}
            row["editable"] = True
            insp = DEMO["inspector"].get(r["id"], DEMO["default_inspector"])
            row["inspector"] = insp
        v1 = _scale(r.get("v1"), basis)
        v2 = _scale(r.get("v2"), basis)
        ov = _OVERRIDES.get(r["id"])
        if ov and kind == "item":
            v1 = ov.get("value", v1)
            row["status"] = "edited"
            row["formula"] = ov.get("formula")
        row["v1"] = v1
        row["v2"] = v2
        rows.append(row)
    viewer = deepcopy(_VIEWER.get(statement, _VIEWER["balance_sheet"]))
    if locale != "en":
        viewer["subtitle"] = tr(viewer["subtitle"], locale)
        viewer["callout"] = tr(viewer["callout"], locale)
    return {
        "statement": statement, "label": localize_label(st["label"], locale), "basis": basis,
        "periods": proj["periods"], "currency": proj["currency"],
        "currency_symbol": proj["currency_symbol"], "units": proj["units"],
        "rows": rows, "viewer": viewer,
    }


class EditBody(BaseModel):
    value: float | None = None
    formula: str | None = None


@router.patch("/{project_id}/line-items/{item_id}",
              dependencies=[Depends(require(Permission.EXTRACTION_EDIT))])
def edit_line_item(project_id: str, item_id: str, body: EditBody) -> dict:
    value = None if body.value is None else round(body.value)
    _OVERRIDES[item_id] = {"value": value, "formula": body.formula or ""}
    return {"id": item_id, "value": value, "formula": body.formula or "", "status": "edited"}


@router.delete("/{project_id}/line-items/{item_id}",
               dependencies=[Depends(require(Permission.EXTRACTION_EDIT))])
def revert_line_item(project_id: str, item_id: str) -> dict:
    _OVERRIDES.pop(item_id, None)
    return {"id": item_id, "reverted": True}


@router.get("/{project_id}/notes")
def get_notes(project_id: str, locale: str = Query("en")) -> dict:
    notes = deepcopy(DEMO["notes_index"])
    if locale != "en":
        for n in notes:
            n["title"] = tr(n["title"], locale)
    return {"notes": notes, "count": 48, "linked": 96}


@router.get("/{project_id}/notes/{note_no}")
def get_note(project_id: str, note_no: int, locale: str = Query("en")) -> dict:
    detail = DEMO["note_detail"].get(note_no)
    if detail is None:
        idx = next((n for n in DEMO["notes_index"] if n["no"] == note_no), None)
        if idx is None:
            raise HTTPException(404, "Unknown note")
        return {"no": note_no, "title": tr(idx["title"], locale), "rows": [], "reconciliation": None}
    detail = deepcopy(detail)
    if locale != "en":
        detail["title"] = tr(detail["title"], locale)
        detail["linked_label"] = tr(detail["linked_label"], locale)
        detail["reconciliation"] = tr(detail["reconciliation"], locale)
        for r in detail["rows"]:
            r["label"] = tr(r["label"], locale)
    return detail


@router.get("/{project_id}/review")
def get_review(project_id: str, locale: str = Query("en")) -> dict:
    checks = deepcopy(DEMO["review"])
    tabs = deepcopy(DEMO["review_tabs"])
    if locale != "en":
        for c in checks:
            c["title"] = tr(c["title"], locale)
            c["where"] = tr(c["where"], locale)
            c["severity"] = tr(c["severity"], locale)
            c["fix"] = tr(c["fix"], locale)
            c["calc"] = [[tr(row[0], locale), tr(row[1], locale), row[2]] for row in c["calc"]]
        for t in tabs:
            t["label"] = tr(t["label"], locale)
    return {"checks": checks, "tabs": tabs, "summary": DEMO["review_summary"]}


@router.get("/{project_id}/template",
            dependencies=[Depends(require(Permission.CONFIG_TEMPLATE))])
def get_template_tree(project_id: str, locale: str = Query("en")) -> dict:
    tree = deepcopy(DEMO["template_tree"])
    node_config = deepcopy(DEMO["node_config"])
    if locale != "en":
        for node in tree:
            node["label"] = localize_label(node["label"], locale)
        for cfg in node_config.values():
            cfg["breadcrumb"] = tr(cfg["breadcrumb"], locale)
            cfg["label"] = localize_label(cfg["label"], locale)
            cfg["value_type"] = tr(cfg["value_type"], locale)
            cfg["aggregation"] = tr(cfg["aggregation"], locale)
            if "netting" in cfg:
                cfg["netting"]["explain"] = tr(cfg["netting"]["explain"], locale)
    return {"tree": tree, "node_config": node_config, "template": DEMO["project"]["template"]}


@router.get("/{project_id}/export-options")
def get_export_options(project_id: str) -> dict:
    return {"options": DEMO["export_options"]}


@router.get("/{project_id}/commentary",
            dependencies=[Depends(require(Permission.COMMENTARY_VIEW))])
def get_commentary(project_id: str, locale: str = Query("en")) -> dict:
    from app.services.commentary import build_commentary

    c = build_commentary(open_review_items=DEMO["review_summary"]["open"])
    if locale != "en":
        c["headline"] = tr(c["headline"], locale)
        c["assessment"] = tr(c["assessment"], locale)
        c["data_quality"] = tr(c["data_quality"], locale)
        c["basis"] = tr(c["basis"], locale)
        c["strengths"] = [tr(s, locale) for s in c["strengths"]]
        c["weaknesses"] = [tr(w, locale) for w in c["weaknesses"]]
        for mtr in c["metrics"]:
            mtr["label"] = tr(mtr["label"], locale)
        for tnd in c.get("trends", []):
            tnd["label"] = tr(tnd["label"], locale)
    return c


@router.get("/{project_id}/audit",
            dependencies=[Depends(require(Permission.COMMENTARY_VIEW))])
def get_audit(project_id: str) -> dict:
    """Audit trail of LLM/extraction runs for the project, with per-run token usage."""
    from app.services import audit as audit_svc

    seeded = deepcopy(DEMO["audit"]) if project_id == "demo" else []
    live = [e.to_dict() for e in audit_svc.recorded(project_id)]
    entries = live + seeded
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return {"entries": entries}


@router.post("/{project_id}/analysis",
             dependencies=[Depends(require(Permission.ANALYSIS_RUN))])
def run_project_analysis(project_id: str) -> dict:
    """Run a live LLM financial analysis via the configured provider and record it to
    the audit log with the model's input/output token usage. The run id is derived from
    the entity name + timestamp. Analyst-driven (analysts/reviewers/admin)."""
    from app.ports.registry import registry as reg
    from app.services import audit as audit_svc
    from app.services.analysis_llm import build_demo_payload, run_analysis

    settings = get_settings()
    entity = DEMO["project"]["entity"]
    run_id = audit_svc.make_run_id(entity)
    provider_id = settings.llm.provider

    def _fail(detail: str):
        audit_svc.record(project_id, audit_svc.AuditEntry(
            run_id=run_id, entity=entity, action="analysis", provider=provider_id,
            model=settings.llm.model, input_tokens=None, output_tokens=None, status="failed",
        ))
        raise HTTPException(status_code=502, detail=detail)

    try:
        provider = reg.get("llm", provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result, meta = run_analysis(provider, build_demo_payload(), max_tokens=settings.llm.max_tokens)
    except Exception as exc:  # provider not configured / unreachable / bad response
        _fail(f"LLM analysis failed: {exc}")

    entry = audit_svc.record(project_id, audit_svc.AuditEntry(
        run_id=run_id, entity=entity, action="analysis", provider=provider_id,
        model=meta.get("model", settings.llm.model),
        input_tokens=meta.get("input_tokens"), output_tokens=meta.get("output_tokens"),
        status="succeeded",
    ))
    return {"entry": entry.to_dict(), "result": result.model_dump(mode="json")}


@router.post("/{project_id}/submit-review",
             dependencies=[Depends(require(Permission.REVIEW_SUBMIT))])
def submit_for_review(project_id: str) -> dict:
    """Analyst hands the final output to the reviewer. Recorded to the audit log.

    The REVIEW_SUBMIT permission is only granted to the analyst while the review step
    is enabled (see security.effective_permissions), so this 403s once review is off."""
    from app.services import audit as audit_svc

    entity = DEMO["project"]["entity"]
    entry = audit_svc.record(project_id, audit_svc.AuditEntry(
        run_id=audit_svc.make_run_id(entity), entity=entity, action="submit_review",
        provider="—", model="—", input_tokens=None, output_tokens=None, status="succeeded",
    ))
    return {"ok": True, "entry": entry.to_dict()}


class ExportBody(BaseModel):
    format: str = "excel"
    basis: str = "consolidated"
    currency: str = "INR"
    units: str = "crore"
    include: dict = {}


@router.post("/{project_id}/export", dependencies=[Depends(require(Permission.EXPORT_RUN))])
def export_project(project_id: str, body: ExportBody) -> Response:
    statements = DEMO["statements"]
    notes_index = DEMO["notes_index"]
    note_detail = DEMO["note_detail"]
    if body.format == "json":
        data = build_json(statements, notes_index, note_detail,
                          basis=body.basis, currency=body.currency, units=body.units)
        return Response(content=data, media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=extract.json"})
    data = build_xlsx(statements, notes_index, note_detail, basis=body.basis,
                      currency=body.currency, units=body.units, include=body.include)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=spread.xlsx"},
    )

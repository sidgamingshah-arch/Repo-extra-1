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
from app.services.page_scope import scope_counts

# Every project endpoint requires an authenticated caller (session token, or the
# X-Role dev header when enabled). Per-action permissions are enforced with require().
router = APIRouter(prefix="/projects", tags=["projects"],
                   dependencies=[Depends(current_principal)])

# In-memory edit overrides: {line_item_id: {"value": int, "formula": str}}.
_OVERRIDES: dict[str, dict] = {}


def _active() -> bool:
    """Whether the seeded sample project is loaded. Off = greenfield (empty app)."""
    from app.services.settings_state import get_seed_demo

    return get_seed_demo()


# Greenfield placeholder project meta — shape-compatible with the demo project so the
# shell renders, but carrying no data. Screens short-circuit to an empty state via the
# `loaded` flag returned by GET /projects/{id}.
_EMPTY_PROJECT = {
    "id": "demo", "entity": "", "title": "No project yet", "filename": "",
    "pages": 0, "standard": "", "currency": "", "currency_symbol": "", "units": "",
    "periods": ["", ""], "bases": ["consolidated", "standalone"],
    "progress": {"pct": 0, "line_items": 0, "in_review": 0},
    "template": {"key": "", "name": "— none selected —", "line_items": 0},
    "ontology": {"file": "— none —", "rules": 0, "aliases": 0, "status": "none"},
}

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
    if _active():
        return {"project": DEMO["project"], "documents": DEMO["documents"], "loaded": True}
    return {"project": _EMPTY_PROJECT, "documents": [], "loaded": False}


@router.get("/{project_id}/integrity")
def get_integrity(project_id: str, locale: str = Query("en")) -> dict:
    if not _active():
        return {"score": 0, "grade": "", "summary": "", "stats": [], "issues": []}
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
    if not _active():
        return {"pages": [], "filters": [], "focused": 0, "total": 0, "skipped": 0}
    pages = deepcopy(DEMO["pages"])
    # Counted from the cards rather than served as literals: this route used to answer
    # `focused: 14, total: 84, skipped: 70` over ten page cards.
    counts = scope_counts(pages)
    if locale != "en":
        for p in pages:
            p["cls"] = tr(p["cls"], locale)
            p["sub"] = tr(p["sub"], locale)
        for f in counts["filters"]:
            f["label"] = tr(f["label"], locale)
    return {"pages": pages, **counts}


# Every statement the app can ask for. The sample project carries only some of them.
_KNOWN_STATEMENTS = ("balance_sheet", "profit_and_loss", "cash_flow", "changes_in_equity")


def _scale(v, basis: str):
    if v is None:
        return None
    return v if basis == "consolidated" else round(v * _STD_SCALE)


@router.get("/{project_id}/statements/{statement}")
def get_statement(project_id: str, statement: str,
                  basis: str = Query("consolidated"),
                  locale: str = Query("en")) -> dict:
    if not _active():
        return {"statement": statement, "label": "", "basis": basis, "periods": ["", ""],
                "currency": "", "currency_symbol": "", "units": "", "rows": [],
                "viewer": {"company": "", "subtitle": "", "chips": [], "callout": ""}}
    st = DEMO["statements"].get(statement)
    if st is None:
        # A statement the app knows about but this sample does not carry (the demo has no
        # statement of changes in equity) is an EMPTY statement, not an error — the tab exists
        # for every document, and 404 would surface as a failure rather than "nothing here".
        if statement in _KNOWN_STATEMENTS:
            return {"statement": statement, "label": "", "basis": basis, "periods": ["", ""],
                    "currency": "", "currency_symbol": "", "units": "", "rows": [],
                    "viewer": {"company": "", "subtitle": "", "chips": [], "callout": ""}}
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
    if not _active():
        return {"notes": [], "count": 0, "linked": 0}
    notes = deepcopy(DEMO["notes_index"])
    if locale != "en":
        for n in notes:
            n["title"] = tr(n["title"], locale)
    # Both counted, not asserted: the header used to read "48 notes · linked to 96 line items"
    # above a list of twelve. `linked` is the number of statement lines that cite one of these
    # notes, which is the same quantity the real route derives from a run's own rows.
    return {"notes": notes, "count": len(notes), "linked": _demo_linked_lines(notes)}


def _demo_linked_lines(notes: list[dict]) -> int:
    """Statement line items citing one of `notes` — the sample's answer to "linked to N lines"."""
    cited = {str(n["no"]) for n in notes}
    return sum(1 for s in DEMO["statements"].values() for r in s["rows"]
               if str(r.get("note") or "") in cited)


@router.get("/{project_id}/notes/{note_no}")
def get_note(project_id: str, note_no: int, locale: str = Query("en")) -> dict:
    if not _active():
        return {"no": note_no, "title": "", "rows": [], "reconciliation": None}
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
    if not _active():
        return {"checks": [], "tabs": [], "summary": {"open": 0, "resolved": 0, "total": 0}}
    checks = deepcopy(DEMO["review"])
    tabs = _demo_review_tabs(checks)
    if locale != "en":
        for c in checks:
            c["title"] = tr(c["title"], locale)
            c["where"] = tr(c["where"], locale)
            c["severity"] = tr(c["severity"], locale)
            c["fix"] = tr(c["fix"], locale)
            c["calc"] = [[tr(row[0], locale), tr(row[1], locale), row[2]] for row in c["calc"]]
        for t in tabs:
            t["label"] = tr(t["label"], locale)
    return {"checks": checks, "tabs": tabs, "summary": _demo_review_summary(checks)}


# Tab labels for the sample's check types, in the order the tabs are shown. The COUNTS are never
# written here — see `_demo_review_tabs`.
_DEMO_TAB_LABELS = (("balance", "Balance check"), ("subtotal", "Subtotals"),
                    ("sign", "Sign anomalies"), ("note", "Note reconciliation"))


def _demo_review_tabs(checks: list[dict]) -> list[dict]:
    """One tab per check type, counted from `checks`, and carrying the type it selects.

    The literals these replace claimed "All 12 · Balance check 1 · Subtotals 4 · Sign anomalies 3
    · Note reconciliation 4" over a list of four checks, one of each type. `types` is what the
    client filters by — see the same field on the real route in api/routes/documents.py.
    """
    return [{"label": "All", "count": len(checks), "types": None}] + [
        {"label": label, "count": sum(1 for c in checks if c.get("type") == kind),
         "types": [kind]}
        for kind, label in _DEMO_TAB_LABELS]


def _demo_review_summary(checks: list[dict]) -> dict:
    """`open` is the findings actually served; `passed` the statement lines they do NOT indict.

    `open: 12, passed: 136` were literals over four checks. `passed` mirrors the real route's
    definition (rows that raised nothing) rather than being a second, unrelated number.
    """
    lines = sum(1 for s in DEMO["statements"].values() for r in s["rows"] if r.get("kind") == "item")
    return {"open": len(checks), "passed": max(0, lines - len(checks))}


@router.get("/{project_id}/template",
            dependencies=[Depends(current_principal)])
def get_template_tree(project_id: str, locale: str = Query("en")) -> dict:
    # Viewing the template structure is reference information any authenticated worker
    # needs (the analyst selects into it). Authoring/editing stays admin-only, enforced
    # on the write endpoints (POST /templates, CONFIG_TEMPLATE).
    if not _active():
        return {"tree": [], "node_config": {}, "template": _EMPTY_PROJECT["template"]}
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
    if not _active():
        return {"headline": "", "assessment": "", "metrics": [], "trends": [],
                "strengths": [], "weaknesses": [], "data_quality": "", "basis": ""}
    from app.services.commentary import build_commentary

    # The findings actually served, not a stored total: the commentary reads how many are open.
    c = build_commentary(open_review_items=len(DEMO["review"]))
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

    seeded = deepcopy(DEMO["audit"]) if (project_id == "demo" and _active()) else []
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

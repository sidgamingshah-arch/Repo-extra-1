"""Seeded demo-project endpoints — the data the workspace/review/notes/export views
render. Uploaded documents use the real pipeline (documents/extractions routers);
this router serves the reviewed Ind-AS sample project end-to-end.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.sample.demo import CONF_PCT, DEMO, localize_label
from app.services import checks as checks_engine
from app.services.export import build_json, build_xlsx

router = APIRouter(prefix="/projects", tags=["projects"])

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
def get_integrity(project_id: str) -> dict:
    return DEMO["integrity"]


@router.get("/{project_id}/pages")
def get_pages(project_id: str) -> dict:
    return {"pages": DEMO["pages"], "filters": DEMO["page_filters"],
            "focused": 14, "total": 84, "skipped": 70}


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
    return {
        "statement": statement, "label": localize_label(st["label"], locale), "basis": basis,
        "periods": proj["periods"], "currency": proj["currency"],
        "currency_symbol": proj["currency_symbol"], "units": proj["units"],
        "rows": rows, "viewer": _VIEWER.get(statement, _VIEWER["balance_sheet"]),
    }


class EditBody(BaseModel):
    value: float | None = None
    formula: str | None = None


@router.patch("/{project_id}/line-items/{item_id}")
def edit_line_item(project_id: str, item_id: str, body: EditBody) -> dict:
    value = None if body.value is None else round(body.value)
    _OVERRIDES[item_id] = {"value": value, "formula": body.formula or ""}
    return {"id": item_id, "value": value, "formula": body.formula or "", "status": "edited"}


@router.delete("/{project_id}/line-items/{item_id}")
def revert_line_item(project_id: str, item_id: str) -> dict:
    _OVERRIDES.pop(item_id, None)
    return {"id": item_id, "reverted": True}


@router.get("/{project_id}/notes")
def get_notes(project_id: str) -> dict:
    return {"notes": DEMO["notes_index"], "count": 48, "linked": 96}


@router.get("/{project_id}/notes/{note_no}")
def get_note(project_id: str, note_no: int) -> dict:
    detail = DEMO["note_detail"].get(note_no)
    if detail is None:
        idx = next((n for n in DEMO["notes_index"] if n["no"] == note_no), None)
        if idx is None:
            raise HTTPException(404, "Unknown note")
        return {"no": note_no, "title": idx["title"], "rows": [], "reconciliation": None}
    return detail


@router.get("/{project_id}/review")
def get_review(project_id: str) -> dict:
    return {"checks": DEMO["review"], "tabs": DEMO["review_tabs"], "summary": DEMO["review_summary"]}


@router.get("/{project_id}/template")
def get_template_tree(project_id: str) -> dict:
    return {"tree": DEMO["template_tree"], "node_config": DEMO["node_config"],
            "template": DEMO["project"]["template"]}


@router.get("/{project_id}/export-options")
def get_export_options(project_id: str) -> dict:
    return {"options": DEMO["export_options"]}


class ExportBody(BaseModel):
    format: str = "excel"
    basis: str = "consolidated"
    currency: str = "INR"
    units: str = "crore"
    include: dict = {}


@router.post("/{project_id}/export")
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

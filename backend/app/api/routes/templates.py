"""Template CRUD (versioned) with schema validation on create.

Templates are authored two ways, and both land in the same validated, versioned place: a JSON
definition, or the Excel workbook a reviewer edits (see services.template_xlsx) — which is the
route an analyst actually uses, because deciding what a spread should contain is a
spreadsheet job, not a JSON one.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db
from app.schemas.loader import load_template, validate_template
from app.security import Permission, require

router = APIRouter(prefix="/templates", tags=["templates"])

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TemplateCreate(BaseModel):
    definition: dict


def _publish(session: Session, definition: dict) -> dict:
    """Validate a definition and store it as the next version of its template key."""
    from app.db.models import TemplateVersion

    try:
        template = load_template(definition)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid template schema: {exc}") from exc

    errors = validate_template(template)
    if errors:
        raise HTTPException(status_code=422,
                            detail={"errors": [e.model_dump() for e in errors]})

    max_ver = session.execute(
        select(func.max(TemplateVersion.version))
        .where(TemplateVersion.template_key == template.template_key)
    ).scalar()
    version = (max_ver or 0) + 1

    row = TemplateVersion(
        template_key=template.template_key,
        name=template.name,
        version=version,
        definition=definition,
    )
    session.add(row)
    session.commit()
    return {"id": row.id, "template_key": template.template_key, "name": template.name,
            "version": version,
            "line_items": len([n for n in template.all_nodes() if n.role.value != "header"])}


@router.post("", status_code=201, dependencies=[Depends(require(Permission.CONFIG_TEMPLATE))])
def create_template(body: TemplateCreate, session: Session = Depends(db)) -> dict:
    return _publish(session, body.definition)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


@router.get("/{template_id}/xlsx")
def download_template_xlsx(template_id: str, session: Session = Depends(db)) -> Response:
    """The template as an editable workbook — one row per line, with the extracted-vs-calculated
    column and each calculated line's components. Upload the edited file back to /templates/xlsx."""
    from app.db.models import TemplateVersion
    from app.services.template_xlsx import build_template_xlsx

    row = session.get(TemplateVersion, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    data = build_template_xlsx(row.definition or {}, filename_hint=row.name or row.template_key)
    fname = f"{_slug(row.template_key) or 'template'}_v{row.version}_template.xlsx"
    return Response(content=data, media_type=_XLSX_MIME,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/xlsx", status_code=201,
             dependencies=[Depends(require(Permission.CONFIG_TEMPLATE))])
async def create_template_from_xlsx(
    file: UploadFile = File(...),
    template_key: str = Form(""),
    name: str = Form(""),
    session: Session = Depends(db),
) -> dict:
    """An edited template workbook → a NEW template version.

    Uploading onto an existing ``template_key`` publishes the next version of it rather than
    replacing anything: a past extraction still explains itself against the version it actually
    ran with. Leave the key blank to start a new template from the workbook's own name.
    """
    from app.services.template_xlsx import TemplateSheetError, parse_template_xlsx

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    stem = re.sub(r"\.(xlsx|xlsm)$", "", file.filename or "template", flags=re.IGNORECASE)
    title = (name or stem).strip() or "Template"
    key = _slug(template_key) or _slug(title) or "template"
    try:
        definition = parse_template_xlsx(raw, template_key=key, name=title)
    except TemplateSheetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — a corrupt/foreign workbook
        raise HTTPException(
            status_code=422,
            detail=f"That file could not be read as a template workbook ({exc}). Download the "
                   f"current template, edit it, and upload that.") from exc
    return _publish(session, definition)


@router.get("/xlsx/columns")
def template_xlsx_columns() -> dict:
    """What the workbook's columns mean — so the upload screen can state the contract it enforces
    instead of the user discovering it from a 422."""
    from app.services.template_xlsx import COLUMNS, KIND_CALCULATED, KIND_EXTRACTED, KIND_HEADING

    return {
        "columns": [{"key": k, "header": h} for k, h in COLUMNS],
        "kinds": [
            {"value": KIND_EXTRACTED,
             "help": "Read off the document by the mapper."},
            {"value": KIND_CALCULATED,
             "help": "Computed from other lines and never mapped; needs 'Calculated from'."},
            {"value": KIND_HEADING, "help": "A section heading; carries no figure."},
        ],
        "required": ["Statement", "Canonical key", "Label (en)", "Kind"],
    }


@router.get("")
def list_templates(session: Session = Depends(db)) -> list[dict]:
    from app.db.models import TemplateVersion

    rows = session.execute(select(TemplateVersion)).scalars().all()
    return [{"id": r.id, "template_key": r.template_key, "name": r.name,
             "version": r.version, "is_published": r.is_published} for r in rows]


@router.get("/{template_id}")
def get_template(template_id: str, session: Session = Depends(db)) -> dict:
    from app.db.models import TemplateVersion

    row = session.get(TemplateVersion, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"id": row.id, "template_key": row.template_key, "version": row.version,
            "definition": row.definition}


_SIGN_UI = {"natural": "as_reported", "as_reported": "as_reported",
            "contra": "expense_contra", "expense_contra": "expense_contra",
            "expense_negative": "expense_contra"}

# A stored SignConvention → the three-way choice the Template screen shows. The ontology is
# the extraction rulebook, so its sign_rule wins over the template's static hint — otherwise an
# edit saved to the ontology would appear to do nothing on screen.
_ONT_SIGN_UI = {
    "natural": "as_reported", "natural_positive": "as_reported", "debit_positive": "as_reported",
    "natural_negative": "expense_contra", "credit_positive": "expense_contra",
    "context": "auto",
}


def _loc(node: dict, locale: str) -> str:
    return (node.get("label_i18n") or {}).get(locale) or node.get("label") or ""


@router.get("/{template_id}/detail")
def get_template_detail(template_id: str, locale: str = "en",
                        session: Session = Depends(db)) -> dict:
    """Render a REAL configured template into the tree + per-node config the Template &
    Ontology screen shows — so an admin sees the seeded/authored template instead of an
    empty screen (the demo-bound view only ever showed demo data). Aliases, sign convention
    and any note-decomposition rule are pulled from the ontology that targets this template."""
    from app.db.models import OntologyVersion, TemplateVersion

    row = session.get(TemplateVersion, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    tdef = row.definition or {}

    # The ontology that targets this template (latest version) supplies aliases/sign/netting.
    from app.schemas.loader import load_ontology

    ont_row = session.execute(
        select(OntologyVersion)
        .where(OntologyVersion.target_template_key == row.template_key)
        .order_by(OntologyVersion.version.desc())
    ).scalars().first()
    by_key = {}
    netting_rules: list[dict] = []
    if ont_row:
        try:
            ont = load_ontology(ont_row.definition)
            for m in ont.mappings:
                by_key[m.canonical_key] = m
            # Generic containment-netting policies (LLM-gated) — surfaced for the admin to review.
            def _lbl(k: str) -> str:
                mm = by_key.get(k)
                return (mm.label if mm and mm.label else k.replace("_", " "))
            for nr in ont.netting_rules:
                netting_rules.append({
                    "id": nr.id, "target_key": nr.target_key, "target_label": _lbl(nr.target_key),
                    "subtract": [{"key": k, "label": _lbl(k)} for k in nr.subtract_keys],
                    "add": [{"key": k, "label": _lbl(k)} for k in nr.add_keys],
                    "condition": nr.condition, "label": nr.label,
                })
        except Exception:  # noqa: BLE001 — a malformed ontology shouldn't blank the screen
            by_key = {}

    tree: list[dict] = []
    node_config: dict[str, dict] = {}
    leaves = 0
    for stmt in tdef.get("statements", []):
        stmt_label = _loc(stmt, locale) or str(stmt.get("type", "")).replace("_", " ").title()
        tree.append({"id": f"stmt:{stmt.get('type')}", "label": stmt_label, "lvl": 0, "head": True})
        for sec in stmt.get("sections", []):
            sec_label = _loc(sec, locale)
            tree.append({"id": f"sec:{sec.get('node_id', sec_label)}", "label": sec_label,
                         "lvl": 1, "head": True})
            for child in sec.get("children", []):
                key = child.get("canonical_key")
                if not key:
                    continue
                leaves += 1
                m = by_key.get(key)
                decomp = getattr(m, "decomposition_rule", None) if m else None
                tree.append({"id": key, "label": _loc(child, locale), "lvl": 2,
                             "rule": bool(decomp)})
                # `aliases` is the merged display set (locale + English fallback, capped).
                # `aliases_locale` is the RAW list stored for this locale — what the editor
                # loads and writes back, so saving zh aliases can't absorb the en fallbacks.
                default_locale = "en"
                if m is not None:
                    raw_i18n = m.aliases_i18n.get(locale)
                    aliases_locale = list(
                        raw_i18n if raw_i18n is not None
                        else (m.aliases if locale == default_locale else [])
                    )
                else:
                    aliases_locale = []
                node_config[key] = {
                    "breadcrumb": f"{stmt_label} / {sec_label}",
                    "label": _loc(child, locale),
                    "canonical_key": key,
                    "aliases_locale": aliases_locale,
                    "aliases": (m.aliases_for(locale) if m else [])[:12],
                    "sign": (
                        _ONT_SIGN_UI.get(str(m.sign_rule.convention.value), "as_reported")
                        if m is not None and (m.sign_rule.convention.value or "") != "natural"
                        else _SIGN_UI.get(str(child.get("sign", "natural")), "auto")
                    ),
                    # The criteria the LLM reasons over, so the editor can show and change what
                    # actually drives meaning-based mapping rather than only string matching.
                    "definition": (m.definition or m.description or "") if m else "",
                    "include": list(m.include) if m else [],
                    "exclude": list(m.exclude) if m else [],
                    "confusable_with": list(m.confusable_with) if m else [],
                    "value_scope": (m.value_scope if m else "exclusive_leaf"),
                    "keyword_hints": list(m.keyword_hints) if m else [],
                    "regex_hints": list(m.regex_hints) if m else [],
                    "exclude_hints": list(m.exclude_hints) if m else [],
                    "value_type": "Monetary",
                    "aggregation": "Sum of children" if child.get("role") in ("subtotal", "total")
                                   else "Direct value",
                    "netting": {"expr": "", "explain": decomp or "No note-decomposition rule for this concept."},
                }

    return {"tree": tree, "node_config": node_config, "netting_rules": netting_rules,
            # Which ontology version supplied the aliases/sign above — the editor PATCHes this
            # id, and `locale` tells it which alias list it is editing.
            "ontology": ({"id": ont_row.id, "ontology_key": ont_row.ontology_key,
                          "version": ont_row.version, "locale": locale} if ont_row else None),
            "template": {"key": row.template_key, "name": row.name, "line_items": leaves}}

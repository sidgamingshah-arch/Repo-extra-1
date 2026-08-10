"""Ontology CRUD (versioned). Create validates keys resolve against the template."""
from __future__ import annotations

import copy
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db
from app.schemas.loader import (
    load_ontology,
    load_template,
    validate_ontology_against_template,
)
from app.security import Permission, require

router = APIRouter(prefix="/ontologies", tags=["ontologies"])


class OntologyCreate(BaseModel):
    definition: dict


@router.post("", status_code=201, dependencies=[Depends(require(Permission.CONFIG_ONTOLOGY))])
def create_ontology(body: OntologyCreate, session: Session = Depends(db)) -> dict:
    from app.db.models import OntologyVersion, TemplateVersion

    try:
        ontology = load_ontology(body.definition)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid ontology schema: {exc}") from exc

    # Validate against the latest matching template version.
    tpl_row = session.execute(
        select(TemplateVersion)
        .where(TemplateVersion.template_key == ontology.target_template_key)
        .order_by(TemplateVersion.version.desc())
    ).scalars().first()
    if tpl_row is None:
        raise HTTPException(
            status_code=422,
            detail=f"Target template {ontology.target_template_key!r} not found",
        )
    template = load_template(tpl_row.definition)
    errors = validate_ontology_against_template(ontology, template)
    if errors:
        raise HTTPException(status_code=422,
                            detail={"errors": [e.model_dump() for e in errors]})

    max_ver = session.execute(
        select(func.max(OntologyVersion.version))
        .where(OntologyVersion.ontology_key == ontology.ontology_key)
    ).scalar()
    version = (max_ver or 0) + 1
    row = OntologyVersion(
        ontology_key=ontology.ontology_key,
        target_template_key=ontology.target_template_key,
        version=version,
        definition=body.definition,
    )
    session.add(row)
    session.commit()
    return {"id": row.id, "ontology_key": ontology.ontology_key, "version": version}


@router.get("")
def list_ontologies(session: Session = Depends(db)) -> list[dict]:
    from app.db.models import OntologyVersion

    rows = session.execute(select(OntologyVersion)).scalars().all()
    return [{"id": r.id, "ontology_key": r.ontology_key,
             "target_template_key": r.target_template_key, "version": r.version}
            for r in rows]


@router.get("/{ontology_id}")
def get_ontology(ontology_id: str, session: Session = Depends(db)) -> dict:
    """Full stored definition — what the frontend editor loads to edit a concept's rules."""
    from app.db.models import OntologyVersion

    row = session.get(OntologyVersion, ontology_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ontology not found")
    return {"id": row.id, "ontology_key": row.ontology_key,
            "target_template_key": row.target_template_key, "version": row.version,
            "definition": row.definition}


class MappingEdit(BaseModel):
    """An inline edit to ONE concept's mapping rules. Only provided fields change.

    ``aliases`` is locale-scoped: it replaces that locale's ``aliases_i18n`` list (and the
    base ``aliases`` list when the locale is the ontology's own default), so editing the
    Chinese aliases can never silently clobber the English ones.
    """

    canonical_key: str
    locale: str | None = None
    aliases: list[str] | None = None
    sign_convention: str | None = None
    label: str | None = None
    description: str | None = None
    # The criteria the LLM actually reasons over. Aliases only help when the printed wording
    # is close to one; `definition`/`include`/`exclude`/`confusable_with` are what let a
    # caption be resolved by MEANING, so they have to be editable too or an analyst can only
    # ever tune string matching.
    definition: str | None = None
    include: list[str] | None = None
    exclude: list[str] | None = None
    confusable_with: list[str] | None = None
    value_scope: str | None = None
    # Lexical rule hints (regex / keyword), the deterministic tier's controls.
    keyword_hints: list[str] | None = None
    regex_hints: list[str] | None = None
    exclude_hints: list[str] | None = None


_VALUE_SCOPES = {"exclusive_leaf", "exclusive_child", "exclusive_residual", "not_applicable"}


def _clean_list(items: list[str] | None) -> list[str]:
    """Trim, drop blanks, de-duplicate — preserving the editor's ordering."""
    return list(dict.fromkeys(i.strip() for i in (items or []) if i and i.strip()))


# UI sign vocabulary → a real SignConvention value (app.core.models.enums.SignConvention).
# "auto" means let the pipeline decide from surrounding context rather than forcing a sign.
_SIGN_FROM_UI = {
    "as_reported": "natural_positive",
    "expense_contra": "natural_negative",
    "auto": "context",
}


def _publish_new_version(session: Session, row, definition: dict) -> dict:
    """Validate an edited definition and store it as the NEXT version of the same ontology.

    Shared by every inline edit so validation can never be skipped on one path: a run
    references the exact version it used, so edits must add a version rather than mutate one.
    """
    from app.db.models import OntologyVersion, TemplateVersion

    try:
        ontology = load_ontology(definition)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422,
                            detail=f"Edit produced an invalid ontology: {exc}") from exc

    tpl_row = session.execute(
        select(TemplateVersion)
        .where(TemplateVersion.template_key == ontology.target_template_key)
        .order_by(TemplateVersion.version.desc())
    ).scalars().first()
    if tpl_row is not None:
        errors = validate_ontology_against_template(ontology, load_template(tpl_row.definition))
        if errors:
            raise HTTPException(status_code=422,
                                detail={"errors": [e.model_dump() for e in errors]})

    max_ver = session.execute(
        select(func.max(OntologyVersion.version))
        .where(OntologyVersion.ontology_key == row.ontology_key)
    ).scalar()
    definition["ontology_key"] = row.ontology_key
    new_row = OntologyVersion(
        ontology_key=row.ontology_key,
        target_template_key=row.target_template_key,
        version=(max_ver or 0) + 1,
        definition=definition,
    )
    session.add(new_row)
    session.commit()
    return {"id": new_row.id, "ontology_key": new_row.ontology_key,
            "version": new_row.version}

@router.patch("/{ontology_id}/mappings",
              dependencies=[Depends(require(Permission.CONFIG_ONTOLOGY))])
def edit_ontology_mapping(ontology_id: str, body: MappingEdit,
                          session: Session = Depends(db)) -> dict:
    """Apply an inline concept edit by publishing a NEW ontology version.

    Versioned rather than in-place: an extraction run references the exact version it used,
    so mutating a stored definition would retroactively change how past runs are explained.
    The edit is re-validated against the target template before it is published, so the
    editor cannot persist an ontology the pipeline would then reject.
    """
    from app.db.models import OntologyVersion, TemplateVersion

    row = session.get(OntologyVersion, ontology_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    definition = copy.deepcopy(row.definition or {})
    mappings = definition.get("mappings")
    if not isinstance(mappings, list):
        raise HTTPException(status_code=422, detail="Ontology has no mappings to edit")

    target = next((m for m in mappings
                   if m.get("canonical_key") == body.canonical_key), None)
    if target is None:
        raise HTTPException(status_code=404,
                            detail=f"Concept {body.canonical_key!r} not in this ontology")

    if body.aliases is not None:
        # Drop blanks / dupes while preserving the admin's ordering.
        cleaned = list(dict.fromkeys(a.strip() for a in body.aliases if a and a.strip()))
        locale = body.locale or definition.get("locale") or "en"
        i18n = dict(target.get("aliases_i18n") or {})
        i18n[locale] = cleaned
        target["aliases_i18n"] = i18n
        # The base list mirrors the default locale (what non-localized consumers read).
        if locale == (definition.get("locale") or "en"):
            target["aliases"] = cleaned

    if body.sign_convention is not None:
        mapped = _SIGN_FROM_UI.get(body.sign_convention)
        if mapped is None:
            raise HTTPException(status_code=422,
                                detail=f"Unknown sign convention {body.sign_convention!r}")
        rule = dict(target.get("sign_rule") or {})
        rule["convention"] = mapped
        target["sign_rule"] = rule

    if body.label is not None:
        target["label"] = body.label
    if body.description is not None:
        target["description"] = body.description
    if body.definition is not None:
        target["definition"] = body.definition
    if body.value_scope is not None:
        if body.value_scope not in _VALUE_SCOPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown value_scope {body.value_scope!r}; expected one of "
                       f"{sorted(_VALUE_SCOPES)}")
        target["value_scope"] = body.value_scope
    if body.confusable_with is not None:
        # These name OTHER concepts; a typo would silently weaken the very disambiguation the
        # field exists for, so unknown keys are rejected rather than stored.
        known = {m.get("canonical_key") for m in mappings}
        unknown = [k for k in body.confusable_with if k and k not in known]
        if unknown:
            raise HTTPException(status_code=422,
                                detail=f"confusable_with names unknown concepts: {unknown}")
        target["confusable_with"] = _clean_list(body.confusable_with)
    for field in ("include", "exclude", "keyword_hints", "exclude_hints"):
        value = getattr(body, field)
        if value is not None:
            target[field] = _clean_list(value)
    if body.regex_hints is not None:
        # A bad pattern would raise inside the matcher on every future run, so it is compiled
        # here and refused now rather than breaking extraction later.
        cleaned = _clean_list(body.regex_hints)
        for pattern in cleaned:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise HTTPException(status_code=422,
                                    detail=f"Invalid regex {pattern!r}: {exc}") from exc
        target["regex_hints"] = cleaned

    out = _publish_new_version(session, row, definition)
    out["canonical_key"] = body.canonical_key
    return out

class NettingRuleEdit(BaseModel):
    """Upsert or delete one containment-netting policy, by rule id.

    Netting decides whether a face line is restated ("cost of sales stated inclusive of
    admin"), so it changes reported figures — it belongs under the same versioned publish and
    validation as a concept edit, never an in-place mutation.
    """

    id: str
    delete: bool = False
    target_key: str | None = None
    subtract_keys: list[str] | None = None
    add_keys: list[str] | None = None
    condition: str | None = None
    label: str | None = None


@router.patch("/{ontology_id}/netting-rules",
              dependencies=[Depends(require(Permission.CONFIG_ONTOLOGY))])
def edit_netting_rule(ontology_id: str, body: NettingRuleEdit,
                      session: Session = Depends(db)) -> dict:
    """Add, change or remove a netting rule, publishing a NEW ontology version."""
    from app.db.models import OntologyVersion

    row = session.get(OntologyVersion, ontology_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ontology not found")

    definition = copy.deepcopy(row.definition or {})
    rules = list(definition.get("netting_rules") or [])
    known = {m.get("canonical_key") for m in (definition.get("mappings") or [])}

    existing = next((r for r in rules if r.get("id") == body.id), None)
    if body.delete:
        if existing is None:
            raise HTTPException(status_code=404, detail=f"No netting rule {body.id!r}")
        rules = [r for r in rules if r.get("id") != body.id]
    else:
        rule = dict(existing or {"id": body.id})
        for field in ("target_key", "condition", "label"):
            value = getattr(body, field)
            if value is not None:
                rule[field] = value
        for field in ("subtract_keys", "add_keys"):
            value = getattr(body, field)
            if value is not None:
                rule[field] = _clean_list(value)
        # Every key must name a real concept — a rule pointing at a non-existent line would
        # silently never fire, which looks identical to a rule that simply did not apply.
        referenced = ([rule.get("target_key")] if rule.get("target_key") else []) \
            + list(rule.get("subtract_keys") or []) + list(rule.get("add_keys") or [])
        unknown = [k for k in referenced if k not in known]
        if unknown:
            raise HTTPException(status_code=422,
                                detail=f"Netting rule references unknown concepts: {unknown}")
        if not rule.get("target_key"):
            raise HTTPException(status_code=422, detail="A netting rule needs a target_key")
        rules = [r for r in rules if r.get("id") != body.id] + [rule]

    definition["netting_rules"] = rules
    return _publish_new_version(session, row, definition)

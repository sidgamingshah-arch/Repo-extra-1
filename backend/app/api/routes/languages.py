"""Supported-languages endpoint — surfaces the multilingual parity registry.

Optionally scoped to a template + ontology so the UI knows which languages are fully
supported (input = output parity) for a given extraction configuration.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import db
from app.schemas.languages import evaluate_parity
from app.schemas.loader import load_ontology, load_template

router = APIRouter(prefix="/languages", tags=["languages"])


@router.get("")
def list_languages(
    template_version_id: str | None = Query(None),
    ontology_version_id: str | None = Query(None),
    session: Session = Depends(db),
) -> dict:
    from app.db.models import OntologyVersion, TemplateVersion

    from sqlalchemy import select

    template = None
    ontology = None
    if template_version_id:
        row = session.get(TemplateVersion, template_version_id)
        if row:
            template = load_template(row.definition)
    if ontology_version_id:
        row = session.get(OntologyVersion, ontology_version_id)
        if row:
            ontology = load_ontology(row.definition, resolve=True)

    # No explicit config → evaluate parity against the latest seeded template + a matching
    # ontology, so the default call reports the real supported set (not an all-False collapse
    # that the UI would otherwise have to paper over).
    if template is None:
        row = session.execute(
            select(TemplateVersion).order_by(TemplateVersion.version.desc())
        ).scalars().first()
        if row:
            template = load_template(row.definition)
    if ontology is None and template is not None:
        from app.services.ontology_select import select_for_template

        # The rulebook IN FORCE, not merely the highest-numbered one — language parity has to
        # describe the aliases a real run would actually use.
        row = select_for_template(session, template.template_key)
        if row:
            ontology = load_ontology(row.definition, resolve=True)

    parity = evaluate_parity(template, ontology)
    return {
        "languages": [
            {**p.model_dump(), "supported": p.supported, "missing": p.missing}
            for p in parity
        ],
        "fully_supported": [p.locale for p in parity if p.supported],
    }

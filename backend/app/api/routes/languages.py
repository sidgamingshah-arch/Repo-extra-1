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

    template = None
    ontology = None
    if template_version_id:
        row = session.get(TemplateVersion, template_version_id)
        if row:
            template = load_template(row.definition)
    if ontology_version_id:
        row = session.get(OntologyVersion, ontology_version_id)
        if row:
            ontology = load_ontology(row.definition)

    parity = evaluate_parity(template, ontology)
    return {
        "languages": [
            {**p.model_dump(), "supported": p.supported, "missing": p.missing}
            for p in parity
        ],
        "fully_supported": [p.locale for p in parity if p.supported],
    }

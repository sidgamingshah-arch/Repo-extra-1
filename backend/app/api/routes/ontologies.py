"""Ontology CRUD (versioned). Create validates keys resolve against the template."""
from __future__ import annotations

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

router = APIRouter(prefix="/ontologies", tags=["ontologies"])


class OntologyCreate(BaseModel):
    definition: dict


@router.post("", status_code=201)
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

"""Template CRUD (versioned) with schema validation on create."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db
from app.schemas.loader import load_template, validate_template
from app.security import Permission, require

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateCreate(BaseModel):
    definition: dict


@router.post("", status_code=201, dependencies=[Depends(require(Permission.CONFIG_TEMPLATE))])
def create_template(body: TemplateCreate, session: Session = Depends(db)) -> dict:
    from app.db.models import TemplateVersion

    try:
        template = load_template(body.definition)
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
        definition=body.definition,
    )
    session.add(row)
    session.commit()
    return {"id": row.id, "template_key": template.template_key, "version": version}


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

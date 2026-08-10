"""Seed reference template + ontology into the DB so extraction runs can attach them.

Loads the shipped HKFRS/IFRS template and its companion ontology (app/sample/templates/)
into the versioned tables if absent — idempotent, safe to call on every startup. This is
what lets an uploaded document be mapped against a real ontology out of the box.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE = _DIR / "hkfrs_hk_china_template.json"
_ONTOLOGY = _DIR / "hkfrs_hk_china_ontology.json"


def ensure_reference_data(session: Session) -> None:
    from app.db.models import OntologyVersion, TemplateVersion

    if not _TEMPLATE.exists() or not _ONTOLOGY.exists():
        return
    tpl = json.loads(_TEMPLATE.read_text())
    ont = json.loads(_ONTOLOGY.read_text())

    # "Already seeded" means ANY version of the key exists, not exactly one: authoring and
    # inline ontology edits publish further versions, and demanding a single row made the next
    # startup after any edit crash on MultipleResultsFound.
    existing_tpl = session.execute(
        select(TemplateVersion).where(TemplateVersion.template_key == tpl["template_key"])
    ).scalars().first()
    if existing_tpl is None:
        session.add(TemplateVersion(
            template_key=tpl["template_key"], name=tpl.get("name", ""), version=1,
            definition=tpl, is_published=True,
        ))

    existing_ont = session.execute(
        select(OntologyVersion).where(OntologyVersion.ontology_key == ont["ontology_key"])
    ).scalars().first()
    if existing_ont is None:
        session.add(OntologyVersion(
            ontology_key=ont["ontology_key"],
            target_template_key=ont["target_template_key"], version=1, definition=ont,
        ))
    session.commit()

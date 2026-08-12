"""Seed reference template + ontologies into the DB so extraction runs can attach them.

Loads the shipped HKFRS/IFRS template and its companion rulebooks (app/sample/templates/) into
the versioned tables if absent — idempotent, safe to call on every startup. This is what lets an
uploaded document be mapped against a real ontology out of the box.

BOTH rulebook generations are seeded and both stay selectable: the v1 ontology, and the v2 one
whose section layer (``section_defaults`` + ``inherits``) the v2 schema adds. They are separate
``ontology_key``s, so neither displaces the other, and an extraction run pins the exact
``OntologyVersion`` row id it used — a run made against v1 goes on resolving to v1 for as long as
that row exists, whatever is seeded beside it.

Every file is put through the checks ``POST /ontologies`` / ``POST /templates`` apply, BEFORE
anything is written. This path used to write whatever was on disk: a shipped file that no longer
loads would then sit in the database as a row the read path chokes on — a 500 on the ontology
editor, or an extraction that reports SUCCEEDED with its structural checks silently gone (see
``loader.unknown_keys``). A startup that fails with the offending path named is the cheaper
failure, and it can only be reached by a defect in the repo's own files.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE = _DIR / "hkfrs_hk_china_template.json"
_ONTOLOGY = _DIR / "hkfrs_hk_china_ontology.json"
_ONTOLOGY_V2 = _DIR / "hkfrs_hk_china_v2_ontology.json"


class ReferenceSeedError(RuntimeError):
    """A shipped reference file cannot be seeded — it would not survive its own upload gate."""


def _load_template(path: Path, raw: dict):
    from app.schemas.loader import load_template, unknown_keys

    try:
        template = load_template(raw)
    except Exception as exc:  # noqa: BLE001 — re-raised with the path that has to be fixed
        raise ReferenceSeedError(f"{path.name} is not a valid template: {exc}") from exc
    stray = unknown_keys(raw, template, limit=10)
    if stray:
        raise ReferenceSeedError(
            f"{path.name} carries keys the template schema does not declare, which would be "
            f"dropped in silence: {stray}")
    return template


def _load_ontology(path: Path, raw: dict, template):
    from app.schemas.loader import load_ontology, unknown_keys, validate_ontology_against_template

    try:
        # ``resolve=True`` on top of plain validation: a v2 concept whose ``inherits`` names no
        # section is not a load error, it is a silent no-op that leaves the concept with no
        # section at all — the one failure mode a shipped rulebook could carry unnoticed.
        ontology = load_ontology(raw)
        load_ontology(raw, resolve=True)
    except Exception as exc:  # noqa: BLE001 — re-raised with the path that has to be fixed
        raise ReferenceSeedError(f"{path.name} is not a valid ontology: {exc}") from exc
    stray = unknown_keys(raw, ontology, limit=10)
    if stray:
        raise ReferenceSeedError(
            f"{path.name} carries keys the ontology schema does not declare, which would be "
            f"dropped in silence: {stray}")
    if ontology.target_template_key == template.template_key:
        errors = validate_ontology_against_template(ontology, template)
        if errors:
            raise ReferenceSeedError(
                f"{path.name} does not validate against {template.template_key!r}: "
                + "; ".join(f"{e.location}: {e.message}" for e in errors[:5]))
    return ontology


def ensure_reference_data(session: Session) -> None:
    from app.db.models import OntologyVersion, TemplateVersion

    if not _TEMPLATE.exists() or not _ONTOLOGY.exists():
        return
    tpl = json.loads(_TEMPLATE.read_text())
    template = _load_template(_TEMPLATE, tpl)

    ontologies: list[dict] = []
    for path in (_ONTOLOGY, _ONTOLOGY_V2):
        if not path.exists():
            continue
        raw = json.loads(path.read_text())
        _load_ontology(path, raw, template)
        ontologies.append(raw)

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

    for ont in ontologies:
        existing_ont = session.execute(
            select(OntologyVersion).where(OntologyVersion.ontology_key == ont["ontology_key"])
        ).scalars().first()
        if existing_ont is None:
            session.add(OntologyVersion(
                ontology_key=ont["ontology_key"],
                target_template_key=ont["target_template_key"], version=1, definition=ont,
            ))
    session.commit()

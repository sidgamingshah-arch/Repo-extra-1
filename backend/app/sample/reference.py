"""Seed the reference template + ontology into the DB so extraction runs can attach them.

Loads the shipped HKFRS/IFRS template and its companion rulebook (app/sample/templates/) into the
versioned tables if absent — idempotent, safe to call on every startup. This is what lets an
uploaded document be mapped against a real ontology out of the box.

ONE template, ONE rulebook. Two generations used to ship side by side — a thin v1 and the v2 that
adds the section layer (``section_defaults`` + ``inherits``), the residual framework and the
validation block — on the reasoning that a run made against v1 should go on resolving to v1. That
reasoning is retired: there is one rulebook, and every concept is authored once in one vocabulary
instead of twice in two. Authoring it twice was not a theoretical cost — a concept written in the
other file's shape was a real defect twice over, caught each time by an invariant test rather than
by review.

Nothing here assumes it is the only rulebook that will ever exist. An uploaded or generated one
takes its place through the same versioned tables, and ``services/ontology_select`` still reads
``metadata.supersedes`` to decide which of several is in force.

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


class ReferenceSeedError(RuntimeError):
    """A shipped reference file cannot be seeded — it would not survive its own upload gate."""


def _load_template(path: Path, raw: dict):
    from app.schemas.loader import load_template, unknown_keys, validate_template

    try:
        template = load_template(raw)
    except Exception as exc:  # noqa: BLE001 — re-raised with the path that has to be fixed
        raise ReferenceSeedError(f"{path.name} is not a valid template: {exc}") from exc
    stray = unknown_keys(raw, template, limit=10)
    if stray:
        raise ReferenceSeedError(
            f"{path.name} carries keys the template schema does not declare, which would be "
            f"dropped in silence: {stray}")
    # The same reference check the upload route runs (``routes.templates._publish``), which this
    # seeder claims to stand in for and did not run: a rollup child naming no node, an identity term
    # naming nothing, a KPI term naming a key the template never declares, a cycle among the KPI
    # intermediates. None of those stop a definition from LOADING — they stop it from ever computing
    # anything, silently, which is precisely what a shipped file must not be allowed to do.
    errors = validate_template(template)
    if errors:
        raise ReferenceSeedError(
            f"{path.name} would be refused by the template upload gate: "
            + "; ".join(f"{e.location}: {e.message}" for e in errors[:10]))
    return template


def _load_ontology(path: Path, raw: dict, template):
    from app.schemas.loader import load_ontology, unknown_keys, validate_ontology_against_template

    try:
        # ``resolve=True`` on top of plain validation: a concept whose ``inherits`` names no
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

    raw_ontology = json.loads(_ONTOLOGY.read_text())
    _load_ontology(_ONTOLOGY, raw_ontology, template)

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
        select(OntologyVersion)
        .where(OntologyVersion.ontology_key == raw_ontology["ontology_key"])
    ).scalars().first()
    if existing_ont is None:
        session.add(OntologyVersion(
            ontology_key=raw_ontology["ontology_key"],
            target_template_key=raw_ontology["target_template_key"], version=1,
            definition=raw_ontology,
        ))
    session.commit()

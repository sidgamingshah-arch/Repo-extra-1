"""Which rulebook is in force for a template.

More than one ontology can target the same template — a v1 written for it and a v2 that replaces
that v1 — and until now every consumer decided for itself, by taking the highest ``version`` among
the matches. That answers the wrong question: ``version`` counts EDITS to one rulebook, so it
cannot compare two different ones. With v1 and v2 both sitting at version 1, the choice fell
through to whichever row the database returned first, which made the product's mapping behaviour a
property of insertion order.

Adoption is declared in the rulebook instead. ``metadata.supersedes`` names the ontology_key this
one replaces, so a rulebook says for itself that it takes over — and the next one takes over from it
without anybody editing code or re-ordering a seed. That is the same principle the rest of this
system runs on: the ontology is data, and a decision about extraction belongs in the data.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session


def _supersedes(definition: dict | None) -> str:
    return str(((definition or {}).get("metadata") or {}).get("supersedes") or "").strip()


def rulebooks_for_template(session: Session, template_key: str) -> list:
    """Every stored ontology targeting ``template_key``, newest edit of each key first."""
    from app.db.models import OntologyVersion

    return list(session.execute(
        select(OntologyVersion)
        .where(OntologyVersion.target_template_key == template_key)
        .order_by(OntologyVersion.ontology_key, OntologyVersion.version.desc())
    ).scalars().all())


def superseded_keys(rows: list) -> set[str]:
    """The ontology_keys that some OTHER present rulebook declares it replaces.

    Only supersession by a rulebook that is actually stored counts. A v2 naming a v1 that was never
    loaded must not silently exclude anything, and a v1 does not become unusable just because a v2
    exists somewhere else.
    """
    present = {r.ontology_key for r in rows}
    return {s for r in rows if (s := _supersedes(r.definition)) and s != r.ontology_key} & present


def select_for_template(session: Session, template_key: str):
    """The rulebook in force for a template, or None when none targets it.

    Three tests, in order:

    1. Drop anything a present rulebook says it replaces.
    2. Prefer a rulebook that DECLARES a supersession over one that declares none. This is what
       separates an adopted successor from a draft: a generated skeleton, or a rulebook someone
       uploaded to try something, replaces nothing and says so by omission. Without this test a
       freshly uploaded skeleton — every concept a stub with no aliases at all — could become the
       rulebook a real extraction runs on, purely because its key happened to sort late.
    3. Then the highest edit version, and finally ontology_key so the answer is at least stable.

    Reaching step 3 with a genuine tie means two adopted rulebooks both claim one template and
    neither replaces the other. That is an authoring question this function cannot answer, and the
    caller sees a definite — if arbitrary — choice rather than an unstable one.
    """
    rows = rulebooks_for_template(session, template_key)
    if not rows:
        return None
    dead = superseded_keys(rows)
    live = [r for r in rows if r.ontology_key not in dead] or rows
    return max(live, key=lambda r: (bool(_supersedes(r.definition)), r.version, r.ontology_key))

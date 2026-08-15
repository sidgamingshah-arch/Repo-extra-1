"""Which rulebook is in force for a template: **the latest one**.

More than one ontology can target the same template, and every consumer used to decide for itself by
taking the highest ``version`` among the matches. That answers the wrong question — ``version`` counts
EDITS to one rulebook, so it cannot compare two different ones — and with two rulebooks both at
version 1 the choice fell through to whichever row the database returned first, making the product's
mapping behaviour a property of insertion order.

The answer is simply the most recently stored one. An admin uploads a rulebook, or corrects a concept
from the Template screen, or start-up refreshes the shipped file: whichever of those happened last is
what the next run maps against. Nothing outranks recency, because there is no honest sense in which
an older rulebook is more current than a newer one.

This module previously ranked on five tests — declared supersession, the shipped key, declaring
anything at all, incumbency, then version — each added to work around the previous one, and their net
effect was that publishing the current rulebook beside an obsolete one changed nothing. What they
were really guarding is a skeleton upload becoming the rulebook a real extraction runs on, and that
belongs at the door rather than in a ranking: ``POST /ontologies`` refuses a rulebook that recognises
nothing, where an author is present to be told why.

``metadata.supersedes`` is still read, and ``superseded_keys`` still reports it, for LABELLING — the
ontology list and a run's record both show whether a rulebook has been declared replaced. That is a
different question from which one runs next, and it no longer decides it.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session


def _supersedes(definition: dict | None) -> str:
    return str(((definition or {}).get("metadata") or {}).get("supersedes") or "").strip()


def _shipped() -> tuple[str, frozenset[str]]:
    """(the shipped ontology_key, the keys the repo retired), read from the shipped set.

    Imported inside the call, like every other import in this module: nothing here should make
    ``services`` depend on ``sample`` at import time, and the answer is cheap (see
    ``reference.shipped_ontology_key``).
    """
    from app.sample.reference import RETIRED_ONTOLOGY_KEYS, shipped_ontology_key

    return shipped_ontology_key(), frozenset(RETIRED_ONTOLOGY_KEYS)


def rulebooks_for_template(session: Session, template_key: str) -> list:
    """Every stored ontology targeting ``template_key``, newest edit of each key first."""
    from app.db.models import OntologyVersion

    return list(session.execute(
        select(OntologyVersion)
        .where(OntologyVersion.target_template_key == template_key)
        .order_by(OntologyVersion.ontology_key, OntologyVersion.version.desc())
    ).scalars().all())


def superseded_keys(rows: list) -> set[str]:
    """The ontology_keys that have been REPLACED, by declaration or by retirement.

    Two ways in, and both require the replacement to be present:

    * some OTHER rulebook in ``rows`` declares it replaces this key. A v2 naming a v1 that was never
      loaded must not silently exclude anything, and a v1 does not become unusable just because a v2
      exists somewhere else.
    * the repo retired the key and the rulebook that replaced it is stored (RETIRED_ONTOLOGY_KEYS).
      The presence condition is the same rule for the same reason: a database holding ONLY
      ``hkfrs_hk_china_v2`` — one whose reference data has not been refreshed yet — must not have
      every rulebook it owns reported as replaced. That would give ``select_for_template`` nothing
      live to choose from and make ``rulebook_record`` label every stored run "superseded".
    """
    present = {r.ontology_key for r in rows}
    dead = {s for r in rows if (s := _supersedes(r.definition)) and s != r.ontology_key} & present
    shipped, retired = _shipped()
    if shipped and shipped in present:
        dead |= (retired & present) - {shipped}
    return dead


def select_for_template(session: Session, template_key: str):
    """The rulebook in force for a template, or None when none targets it.

    ONE TEST: **the latest rulebook wins.** Whatever was stored most recently for this template —
    uploaded by an admin, or published by correcting a concept from the Template screen, or refreshed
    from the shipped file at start-up — is what the next run maps against.

    That is the whole rule, and it replaces five. The five were: drop declared supersessions, prefer
    the shipped key, prefer a rulebook that declares a supersession, prefer the incumbent key, then
    highest version. Every one of them after the first was added to work around the one before it —
    "prefer the shipped key" existed only to defeat "prefer the incumbent", which existed only to
    defeat "highest version", which had let a skeleton win on sort order. A precedence hierarchy
    nobody asked for, whose net effect was that publishing the current 185-concept rulebook beside an
    old 173-concept one changed nothing, because the old one had been seen first and said it
    superseded something.

    THE HOLE THE OLD TESTS WERE REALLY GUARDING was a skeleton upload — every concept a stub with no
    aliases at all — becoming the rulebook a real extraction runs on. That is not a precedence
    question and ranking cannot answer it honestly: a rulebook that recognises nothing is not a
    lower-priority rulebook, it is not a rulebook. It is refused at the door instead, by
    ``POST /ontologies``, where an author is present to be told why (``routes.ontologies``).

    ``created_at`` decides, because "latest" means latest in time and a version number only counts
    edits WITHIN one key — it cannot compare two different rulebooks, which is the mistake this
    module was originally written to fix. Version and id break an exact tie so the answer is stable
    rather than a property of row order.

    A declared supersession no longer changes the outcome, and does not need to: a rulebook that
    replaces another is published after it, so it already wins. ``superseded_keys`` stays, for
    LABELLING only — "has this been declared replaced?" is worth showing on the ontology list and on
    a run's record, and it is a different question from "what runs next".
    """
    rows = rulebooks_for_template(session, template_key)
    if not rows:
        return None
    return max(rows, key=lambda r: (r.created_at, r.version, r.id))

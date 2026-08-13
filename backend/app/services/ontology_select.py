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

One thing a rulebook cannot declare, and this module therefore asks the repo: whether it is the
rulebook the repo SHIPS (``sample.reference.shipped_ontology_key``). A shipped rulebook does not
know which legacy keys some particular database still holds, and the keys it replaced cannot be
expected to declare their own retirement — they were authored before the successor existed. See
``sample.reference.RETIRED_ONTOLOGY_KEYS``, and ``select_for_template`` for why being the shipped
one has to outrank both of the tests below.
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

    Five tests, in order:

    1. Drop anything a present rulebook says it replaces, or that the repo has retired
       (``superseded_keys``).
    2. THE SHIPPED RULEBOOK WINS. Among what survives step 1, the rulebook whose key this repo
       ships is in force — nothing that merely sits in the database outranks the file the product is
       built from.

       This is the test that lets a rulebook revision reach a reader, and the state it was found in
       is why it exists. A database seeded before the one-rulebook consolidation holds
       ``hkfrs_hk_china_v2``, which DECLARES a supersession and was seen FIRST, while the shipped
       ``hkfrs_hk_china`` declares none and arrives later — so it lost at step 3 and again at
       step 4, and publishing the current 185-concept rulebook beside the old one changed nothing.
       The product went on mapping filings with a 173-concept rulebook carrying a tax bucket the
       specification had removed.

       It does not reopen the hole step 4 closes. An arbitrary upload still cannot displace the
       shipped rulebook: taking over is something a rulebook has to SAY, and saying it removes the
       shipped one at step 1, where a declared supersession is honoured whoever declares it.
    3. Prefer a rulebook that DECLARES a supersession over one that declares none. This is what
       separates an adopted successor from a draft: a generated skeleton, or a rulebook someone
       uploaded to try something, replaces nothing and says so by omission. Without this test a
       freshly uploaded skeleton — every concept a stub with no aliases at all — could become the
       rulebook a real extraction runs on, purely because its key happened to sort late.
    4. THE INCUMBENT WINS A TIE. Among rulebooks that all declare nothing, the one that has been
       here longest stays in force, so an upload never takes over by arriving.

       This is what step 3 alone could not do, and the day it mattered is instructive: while two
       generations shipped, the successor declared a supersession and won at step 3 whatever else
       was stored. Consolidating to one rulebook left NOTHING declaring one — step 3 became a tie on
       every template, the next test was "highest version, then ontology_key", and a leftover
       ``hkfrs_hk_china_v1_draft`` skeleton took over from ``hkfrs_hk_china`` because it sorted
       later.
       Extraction went on running, against a rulebook of empty stubs.

       It stays even though step 2 covers the shipped rulebook, because it is the answer for every
       key that is NOT the shipped one: two uploads, neither declaring anything, must not swap
       places on each other's edits.
    5. Then the highest edit version of that key — a later version IS adoption of that key's newer
       content — and finally ontology_key, so a genuine tie is at least stable.

    Reaching step 5 with a genuine tie means two rulebooks first seen in the same instant both claim
    one template and neither replaces the other. That is an authoring question this function cannot
    answer, and the caller sees a definite — if arbitrary — choice rather than an unstable one.
    """
    rows = rulebooks_for_template(session, template_key)
    if not rows:
        return None
    dead = superseded_keys(rows)
    live = [r for r in rows if r.ontology_key not in dead] or rows
    # Incumbency is a property of the KEY, not of one stored version of it: editing a rulebook
    # publishes a new row, and a fresh row for a long-standing key must not read as a newcomer.
    first_seen: dict[str, object] = {}
    for r in live:
        prior = first_seen.get(r.ontology_key)
        if prior is None or r.created_at < prior:
            first_seen[r.ontology_key] = r.created_at
    shipped, _ = _shipped()
    # ``shipped and`` because "" is what an absent sample file answers, and without it every row
    # whose key is empty would be treated as the shipped rulebook.
    return max(live, key=lambda r: (bool(shipped) and r.ontology_key == shipped,
                                    bool(_supersedes(r.definition)),
                                    -first_seen[r.ontology_key].timestamp(),
                                    r.version, r.ontology_key))

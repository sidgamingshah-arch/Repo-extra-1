"""Bring an existing database's reference data back to the files this repo ships.

Written for one database and kept, because the state it repairs can only be reached by a database
that predates the fix and the same state will be reached again by anyone restoring an old copy.
Idempotent: a reconciled database reports "nothing to reconcile" on every later run.

WHAT WENT WRONG. ``sample/reference.ensure_reference_data`` used to publish a version 1 only when no
version of the key existed, and then never look at the shipped files again — so every revision made
after a database's first startup reached the tests (``tests/conftest.py`` points
``FINEX_DATABASE_URL`` at a fresh temp database) and never reached the app using that database. The
development database showed it in every one of its rows:

* all four stored ``hkfrs_hk_china_v1`` template versions carried the PRE-REVISION profit-and-loss,
  whose top-level order is the seven sections followed by every calculated total bunched at the end
  (``pl_gross_profit``, ``pl_operating_profit_ebit``, ``pl_total_expenses``, …). The statement
  builder emits the template's own order faithfully; that order was what it was given. "Gross Profit
  and the other calculated totals still render at the END of the template" was a true report about a
  template four revisions stale.
* the stored rulebook was still the 173-concept ``hkfrs_hk_china_v2`` — the tax sweep bucket still
  there, no "Direct costs" alias, no ``sole_component_of`` — while the shipped file is 185 concepts
  keyed ``hkfrs_hk_china``. The one-rulebook consolidation had never reached the product.
* 16 of the 18 stored ontology versions were Playwright junk. The e2e suite runs uvicorn with
  ``cwd: ../backend``, so its three ontology-editing probes published their ``E2E alias <epoch>`` /
  ``E2E includes <epoch>`` / ``E2E netting <epoch>`` edits straight into the development database
  (frontend/e2e/smoke.spec.ts:300, :329, :366).

``ensure_reference_data`` now refreshes on every boot, so the drift closes by itself. This script is
for the part a startup path must NOT do: deleting. It removes

* every version of an ontology key the shipped set no longer names
  (``sample/reference.RETIRED_ONTOLOGY_KEYS``). They are already retired — the selector will not put
  one in force — but a retired rulebook still sits in ``GET /ontologies`` and still costs the screen
  a quarter-megabyte deserialization per row.
* every remaining ontology version carrying an e2e probe marker, whatever key it is under. The suite
  now edits the SHIPPED key, so this is the rule that keeps working after this one-off cleanup.

and then refreshes the template and the ontology from the files.

WHAT IT DELIBERATELY DOES NOT TOUCH, stated because leaving it unsaid would read as an oversight:
older versions of the SHIPPED template key. None of them carries an e2e marker, one of them is
pinned by a stored extraction run, and the newest version is what every reader gets
(``sortTemplates`` on the Template screen, and a run names the version id it read). An unreferenced
older version is history, not clutter — the same rule ``scripts/prune_ontology_versions.py``
applies. What it prints instead is how many of them there are, so the operator can prune
deliberately.

A run that pinned a rulebook version this deletes is reported BEFORE anything is written: its
rulebook record changes from "superseded" to "missing" (api/routes/extractions.rulebook_record).
That is the price of deleting the junk, and the plan states it rather than discovering it later.

    cd backend
    python scripts/reconcile_reference_data.py                       # report only
    python scripts/reconcile_reference_data.py --db /tmp/copy.db     # …against a copy
    python scripts/reconcile_reference_data.py --apply               # write

Deletion is not reversible, so writing takes ``--apply``. Try it on a copy first
(``cp finex.db /tmp/copy.db``): ``--db`` points every part of this script at that file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# The three ontology-editing e2e probes build their strings as `E2E alias ${Date.now()}` and so on
# (frontend/e2e/smoke.spec.ts:300, :329, :366), which is why an epoch is part of the pattern: it
# cannot match an alias a human authored, and it cannot match the shipped files — the suite asserts
# on these exact strings, so the day one is renamed the rename lands in one place.
_E2E_PROBE = re.compile(r"E2E (?:alias|includes|netting) \d{10,}")

# THIS checkout's backend root, ahead of anything else on the path. Running
# ``python scripts/reconcile_reference_data.py`` puts ``backend/scripts`` on sys.path and NOT
# ``backend``, so ``import app`` resolves through whatever editable install the interpreter can
# see — another checkout, whose ``ensure_reference_data`` may still be the seed-once version this
# script exists to repair the damage from. It would then report a reconciliation it never performed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _concepts(definition: dict | None) -> int:
    return len((definition or {}).get("mappings") or [])


def _pl_order(definition: dict | None) -> list[str]:
    """The profit-and-loss statement's top-level node ids, in stored order.

    Printed because it is the reader-visible face of the drift: the shipped order interleaves each
    calculated total with the section it is computed from, and the stale one puts all of them last.
    """
    for statement in (definition or {}).get("statements") or []:
        if statement.get("type") == "profit_and_loss":
            return [str(s.get("node_id") or "") for s in statement.get("sections") or []]
    return []


def _e2e_markers(definition: dict | None) -> list[str]:
    return sorted(set(_E2E_PROBE.findall(json.dumps(definition or {}, ensure_ascii=False))))


def _summary(session, label: str) -> None:
    """What the database says right now, in the facts the drift showed up in."""
    from sqlalchemy import select

    from app.db.models import OntologyVersion, TemplateVersion
    from app.sample.reference import shipped_ontology_key, shipped_template_key
    from app.services.ontology_select import select_for_template

    tpl_key, ont_key = shipped_template_key(), shipped_ontology_key()
    print(f"\n{label}")
    templates = list(session.execute(
        select(TemplateVersion).where(TemplateVersion.template_key == tpl_key)
        .order_by(TemplateVersion.version)).scalars().all())
    if not templates:
        print(f"  template {tpl_key}: not stored")
    else:
        published = [f"v{r.version}" for r in templates if r.is_published] or ["none"]
        print(f"  template {tpl_key}: {len(templates)} version(s), "
              f"newest v{templates[-1].version}, published {', '.join(published)}")
        order = ", ".join(_pl_order(templates[-1].definition))
        print(f"    P&L top-level order: {order or 'none'}")

    rows = list(session.execute(
        select(OntologyVersion).order_by(OntologyVersion.ontology_key, OntologyVersion.version)
    ).scalars().all())
    in_force = select_for_template(session, tpl_key) if tpl_key else None
    by_key: dict[str, list] = {}
    for r in rows:
        by_key.setdefault(r.ontology_key, []).append(r)
    for key, versions in sorted(by_key.items()):
        mark = " [IN FORCE]" if in_force is not None and in_force.ontology_key == key else ""
        junk = sum(1 for r in versions if _e2e_markers(r.definition))
        print(f"  ontology {key}: {len(versions)} version(s) v{versions[0].version}-"
              f"v{versions[-1].version}, {_concepts(versions[-1].definition)} concepts"
              f"{', ' + str(junk) + ' carrying e2e probe edits' if junk else ''}{mark}")
    if ont_key not in by_key:
        print(f"  ontology {ont_key}: NOT STORED — the shipped rulebook is not in this database")
    if in_force is None:
        print(f"  in force for {tpl_key}: nothing")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Reconcile a database's reference template + ontology to the shipped files.")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete and publish (default is a report)")
    ap.add_argument("--db", default="",
                    help="SQLite file to reconcile (default: the app's configured database). Point "
                         "this at a copy to rehearse.")
    args = ap.parse_args()

    if args.db:
        path = Path(args.db).expanduser().resolve()
        if not path.exists():
            print(f"no such database: {path}")
            return 1
        # Set BEFORE the first app import: ``app.db.base`` builds its engine from the settings at
        # import time and ``get_settings`` is lru_cached, so exporting this afterwards would leave
        # the script reading its own report off the copy while writing to the dev database.
        os.environ["FINEX_DATABASE_URL"] = f"sqlite:///{path}"

    from sqlalchemy import select

    from app.db.base import SessionLocal, engine, init_db
    from app.db.models import ExtractionRun, OntologyVersion
    from app.sample.reference import RETIRED_ONTOLOGY_KEYS, ensure_reference_data

    init_db()
    print(f"database: {engine.url}")
    with SessionLocal() as session:
        _summary(session, "BEFORE")

        rows = list(session.execute(
            select(OntologyVersion).order_by(OntologyVersion.ontology_key, OntologyVersion.version)
        ).scalars().all())
        doomed: list[tuple[object, str]] = []
        for r in rows:
            if r.ontology_key in RETIRED_ONTOLOGY_KEYS:
                doomed.append((r, "retired key: the shipped set no longer names it"))
            elif markers := _e2e_markers(r.definition):
                doomed.append((r, f"e2e probe edit ({markers[0]})"))

        # Reported before the plan is acted on: a run pins the ontology_version_id it read the
        # filing against, and deleting it leaves the run's rulebook record reading "missing".
        referenced = {
            oid for (oid,) in session.execute(
                select(ExtractionRun.ontology_version_id)
                .where(ExtractionRun.ontology_version_id.is_not(None)).distinct())}
        orphaned = [r for r, _ in doomed if r.id in referenced]

        print("\nPLAN — what --apply would do, in this order")
        for r, why in doomed:
            print(f"  delete   ontology {r.ontology_key:22} v{r.version:<4} {why}")
        if not doomed:
            print("  delete   nothing — no retired key and no e2e probe edit is stored")
        # Staged inside the transaction and flushed, so the refresh is planned against the database
        # the deletions leave behind rather than the one they started from — otherwise the plan
        # reports a retired key as "stored but retired" one line under its own deletion, and would
        # miss a republish that only becomes necessary once a polluted newest version is gone.
        for r, _ in doomed:
            session.delete(r)
        session.flush()
        # Printed verbatim: a note is either an action ("published v5 from …") or a finding ("stored
        # but retired"), and prefixing both with one verb of this script's own choosing labelled the
        # findings as work.
        for note in ensure_reference_data(session, dry_run=True):
            print(f"  {note}")
        if orphaned:
            print(f"  NOTE     {len(orphaned)} extraction run(s) pin a rulebook version this "
                  f"deletes; their rulebook record becomes \"missing\"")

        if not args.apply:
            session.rollback()          # the staged deletions, undone: this run wrote nothing
            print("\nreport only — pass --apply to write")
            return 0

        session.commit()
        print("\nAPPLIED")
        for note in ensure_reference_data(session):
            print(f"  {note}")
        _summary(session, "AFTER")
    return 0


if __name__ == "__main__":
    sys.exit(main())

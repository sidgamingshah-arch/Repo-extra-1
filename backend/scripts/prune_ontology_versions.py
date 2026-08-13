"""Drop superseded ontology versions that nothing refers to.

Editing a concept, a criterion or a netting rule PUBLISHES A NEW VERSION rather than mutating the
stored one — that is deliberate, and it is what lets a past extraction still be explained by the
exact rulebook it read (see api/routes/ontologies.py::edit_ontology_mapping). The cost is that a
developer database accumulates them: the three ontology-edit e2e tests publish one apiece on every
suite run, so `hkfrs_hk_china_v2` reached v21 holding 4.5 MB of definitions, all of which
`GET /ontologies` deserializes on every request to report each rulebook's key, version and size.

Two rules, and the second is the one that matters:

* keep the LATEST version of every ontology_key. Not "the latest per template" — every rulebook here
  targets one template, so that would collapse to a single row and delete the v1 rulebook that v2
  declares it supersedes, which is the pair the whole supersession mechanism is demonstrated by.
* keep any version an ExtractionRun REFERENCES, however old. A run pins the ontology_version_id it
  read the filing against; deleting that row would leave the run naming a rulebook that no longer
  exists, and "every downstream number is reproducible" stops being true. A stale-but-referenced
  version is history, not clutter.

Everything else is an intermediate draft nothing points at. Run with --apply to delete; without it
this only reports, because the deletion is not reversible.
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default is a dry run)")
    args = ap.parse_args()

    from sqlalchemy import func, select

    from app.db.base import SessionLocal, init_db
    from app.db.models import ExtractionRun, OntologyVersion

    init_db()
    with SessionLocal() as session:
        rows = session.execute(select(OntologyVersion)).scalars().all()
        if not rows:
            print("no ontology versions stored")
            return 0

        latest: dict[str, int] = {}
        for r in rows:
            latest[r.ontology_key] = max(latest.get(r.ontology_key, 0), r.version)
        referenced = {
            oid for (oid,) in session.execute(
                select(ExtractionRun.ontology_version_id).where(
                    ExtractionRun.ontology_version_id.is_not(None)).distinct())}

        keep, drop = [], []
        for r in rows:
            if r.version == latest[r.ontology_key]:
                keep.append((r, "latest of its rulebook"))
            elif r.id in referenced:
                keep.append((r, "read by an extraction run"))
            else:
                drop.append(r)

        for r, why in sorted(keep, key=lambda kr: (kr[0].ontology_key, kr[0].version)):
            print(f"  keep  {r.ontology_key:22} v{r.version:<4} {why}")
        for r in sorted(drop, key=lambda x: (x.ontology_key, x.version)):
            print(f"  drop  {r.ontology_key:22} v{r.version:<4} superseded, referenced by nothing")

        freed = sum(len(str(r.definition or "")) for r in drop)
        print(f"\n{len(keep)} kept, {len(drop)} to drop (~{freed / 1e6:.1f} MB of definitions)")
        if not drop:
            return 0
        if not args.apply:
            print("dry run — pass --apply to delete")
            return 0

        for r in drop:
            session.delete(r)
        session.commit()
        remaining = session.execute(select(func.count()).select_from(OntologyVersion)).scalar()
        print(f"deleted {len(drop)}; {remaining} ontology versions remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())

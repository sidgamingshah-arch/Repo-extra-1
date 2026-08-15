"""Audit log — run identifiers and an append-only trail of LLM/extraction runs.

Two responsibilities:

  * ``make_run_id(entity)`` mints a human-readable run id from the entity name plus the
    UTC date and time (e.g. ``infosys-limited-20260807-021455``), with a short suffix on
    the rare same-second collision so ids stay unique.
  * A process-local append-only store of :class:`AuditEntry` records — one per run —
    surfaced by ``GET /projects/{id}/audit``. Each entry carries the LLM token usage
    (input and output separately) so cost is auditable per run.

This is a lightweight, in-memory projection for the current foundation; the durable
table (EditEvent / run ledger) documented in the data-model doc is the infra-time swap
and does not change these signatures.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "entity").strip().lower()).strip("-")
    return (s or "entity")[:48]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Run ids already handed out this process — guards against same-second collisions.
_ISSUED: set[str] = set()


def make_run_id(entity: str, *, at: datetime | None = None) -> str:
    """entity-slug + UTC timestamp, e.g. ``infosys-limited-20260807-021455``."""
    ts = (at or _now()).strftime("%Y%m%d-%H%M%S")
    base = f"{_slug(entity)}-{ts}"
    run_id = base
    n = 2
    while run_id in _ISSUED:
        run_id = f"{base}-{n}"
        n += 1
    _ISSUED.add(run_id)
    return run_id


def elapsed_ms(since: datetime) -> int:
    """Milliseconds from ``since`` to now — ONE spelling of "how long did this take".

    Every recording site measures the same quantity the same way, so two entries in one trail cannot
    mean different things by their duration. Never negative: a clock that has gone backwards should
    report "no time at all", not a negative elapsed that renders as a nonsense figure.

    A NAIVE ``since`` IS READ AS UTC, which is what ``_now`` and every other stamp in this codebase
    means. It is not hypothetical: the extraction task reconstructs its start from an ISO string
    (``_run_extraction_task``'s ``started_at``), a stamp that need not carry a zone, and subtracting a
    naive datetime from an aware one raises ``TypeError``. Raising HERE would be raising inside the
    recording of a run's outcome — including the failure path, which would abandon the run row at
    ``running`` and leave a polling client waiting on it for ever. The same normalisation the progress
    payload already applies, for the same reason (``routes.extractions._as_utc``).
    """
    at = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
    return max(0, int((_now() - at).total_seconds() * 1000))


@dataclass
class AuditEntry:
    run_id: str
    entity: str
    action: str                       # "analysis" | "extraction" | "credit_narrative" | …
    provider: str                     # "anthropic" | "openai" | "local" | "stub" | …
    model: str
    input_tokens: int | None          # None when the run used no LLM
    output_tokens: int | None
    status: str = "succeeded"         # "succeeded" | "failed"
    # HOW LONG THE RUN TOOK, in milliseconds, measured by whoever ran it (see :func:`elapsed_ms`).
    #
    # Optional and honestly optional: an entry for something INSTANTANEOUS — a submission handed to
    # a reviewer — has no duration to report, and None renders as "—" rather than as "0 ms", which
    # would read as a measurement of a run that took no time. It stays None on old entries too.
    #
    # Recorded here because the trail is the only place a finished run's duration can be read. The
    # extraction screen's live progress carries `elapsed_ms` while a run is in flight, and that panel
    # is gone the moment results arrive — so "how long did that extraction take?" had no answer at
    # all once it had finished, on the screen whose job is to account for the run.
    duration_ms: int | None = None
    created_at: str = field(default_factory=lambda: _now().isoformat())

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_tokens"] = self.total_tokens
        return d


# project_id -> entries recorded this process (most-recent appended last).
_LOG: dict[str, list[AuditEntry]] = defaultdict(list)


def record(project_id: str, entry: AuditEntry) -> AuditEntry:
    _LOG[project_id].append(entry)
    return entry


def recorded(project_id: str) -> list[AuditEntry]:
    return list(_LOG[project_id])


def served_trail(key: str, seeded: list[dict] | None = None) -> dict:
    """The audit payload for one key — newest first, seeded rows folded in.

    ONE spelling, because two routes serve this: the seeded sample project by its project id, and an
    uploaded document by its document id. Assembling and sorting it separately in each is how the two
    come to disagree about ordering — and ordering is the whole readability of a trail.
    """
    entries = [e.to_dict() for e in recorded(key)] + list(seeded or [])
    entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return {"entries": entries}


def clear(project_id: str | None = None) -> None:
    """Test helper — reset the store (and the issued-id guard)."""
    if project_id is None:
        _LOG.clear()
        _ISSUED.clear()
    else:
        _LOG.pop(project_id, None)

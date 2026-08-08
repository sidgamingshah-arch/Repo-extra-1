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


@dataclass
class AuditEntry:
    run_id: str
    entity: str
    action: str                       # "analysis" | "extraction"
    provider: str                     # "anthropic" | "openai" | "local" | "stub" | …
    model: str
    input_tokens: int | None          # None when the run used no LLM
    output_tokens: int | None
    status: str = "succeeded"         # "succeeded" | "failed"
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


def clear(project_id: str | None = None) -> None:
    """Test helper — reset the store (and the issued-id guard)."""
    if project_id is None:
        _LOG.clear()
        _ISSUED.clear()
    else:
        _LOG.pop(project_id, None)

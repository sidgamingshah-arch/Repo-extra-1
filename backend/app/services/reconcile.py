"""Note→face reconciliation (Requirement 20) — the highest-value logic.

When a detailed item comes from a NOTE and the FACE has an overarching line that
references that note, the face aggregate must be adjusted by **subtracting** the note
detail(s) that are *also* ingested as their own template lines, so nothing is
double-counted and totals tie.

This module implements the arithmetic as pure functions (no I/O) so it is exhaustively
unit- and property-testable. The stage wraps it.

Key invariants:
* Reconciliation is computed **from the raw face value**, never from an already
  reconciled figure → re-running is idempotent.
* Signs are respected: a detail that is itself negative is subtracted with its sign.
* Values must share a unit context before subtraction (caller converts to base units).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class NoteDetail:
    item_id: str
    value: Decimal
    maps_to_distinct_template_line: bool = True  # only these cause double-counting


@dataclass
class ReconcileInput:
    face_item_id: str
    note_number: str
    raw_face_value: Decimal
    details: list[NoteDetail]
    tolerance_abs: Decimal = Decimal(1)
    tolerance_rel: Decimal = Decimal("0.001")
    coverage: Decimal = Decimal(1)          # for 1-note→N-face partitioning


@dataclass
class ReconcileOutput:
    face_item_id: str
    note_number: str
    raw_face: Decimal
    subtracted: Decimal
    reconciled: Decimal
    residual: Decimal
    within_tolerance: bool
    warnings: list[str] = field(default_factory=list)


def tolerance(face: Decimal, abs_eps: Decimal, rel_eps: Decimal) -> Decimal:
    return max(abs_eps, (rel_eps * abs(face)))


def reconcile_face(inp: ReconcileInput) -> ReconcileOutput:
    """Compute the reconciled face value by subtracting the mapped note details.

    ``reconciled = raw_face - Σ(detail.value for details that map to a distinct
    template line)``. The ``residual`` is what remains after also accounting for the
    *full* note (i.e. how far the note total is from the face) — surfaced for review.
    """
    warnings: list[str] = []

    # Dedupe details by id (guards N-notes→1-face double subtraction).
    seen: set[str] = set()
    subtracted = Decimal(0)
    note_total = Decimal(0)
    for d in inp.details:
        if d.item_id in seen:
            warnings.append(f"duplicate detail {d.item_id} ignored")
            continue
        seen.add(d.item_id)
        note_total += d.value
        if d.maps_to_distinct_template_line:
            subtracted += d.value

    reconciled = inp.raw_face_value - subtracted

    # Residual: the "other/unexplained" remainder between face and the FULL note total.
    residual = inp.raw_face_value - note_total
    tol = tolerance(inp.raw_face_value, inp.tolerance_abs, inp.tolerance_rel)
    within = abs(residual) <= tol

    if reconciled < 0:
        warnings.append(
            "reconciled face value is negative — likely over-subtraction or a sign error"
        )

    return ReconcileOutput(
        face_item_id=inp.face_item_id,
        note_number=inp.note_number,
        raw_face=inp.raw_face_value,
        subtracted=subtracted,
        reconciled=reconciled,
        residual=residual,
        within_tolerance=within,
        warnings=warnings,
    )

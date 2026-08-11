"""How an extracted row's values are read — which column is which period, and what figure a
concept actually shows.

Every consumer of an extracted row (the statement view, the Excel export, the note tables, the
accounting checks) has to answer the same two questions, and answering them differently is how a
prior-year figure ends up printed under the current year, or how a validated total stops being
the total on screen. So the answers live here, once.

Extraction labels a value's column as it reads it: ``current`` for the leftmost figure column,
``prior`` for the next, ``colN`` beyond that, and — for a matrix statement such as changes in
equity — the column's own printed heading ("Retained profits"). A row that carries no figure at
all in the current year therefore has values labelled ``prior`` and nothing else, which is
exactly the case the naive "first value is the current one" fallback gets wrong.
"""
from __future__ import annotations

CURRENT = "current"
PRIOR = "prior"


def _named(v: dict) -> str:
    return str(v.get("period_label") or "").strip().lower()


def basis_values(row: dict, basis: str) -> list[dict]:
    """A row's values for one basis; a value with no basis is treated as consolidated."""
    return [v for v in (row.get("values") or [])
            if (v.get("basis") or "consolidated") == basis]


def split_current_prior(vals: list[dict]) -> tuple[dict | None, dict | None]:
    """``(current, prior)`` for one row's values (already filtered to a single basis).

    A value that NAMES its period wins outright, and a period nothing was printed for stays
    ``None``. The positional fallback — first value is current, second is prior — applies only
    when no value in the list names a period at all (columns read as ``col0``/``col1``, or a
    matrix row's component columns), because there the order on the page is the only signal.

    The distinction matters: several filings print a line for one year only (a deposit pledged
    in the prior year and released since). Falling back positionally there takes last year's
    figure and reports it as this year's — inventing a current-year number the document never
    contained, in the one place a reader cannot check it.
    """
    by: dict[str, dict] = {}
    for v in vals:
        lbl = _named(v)
        if lbl in (CURRENT, PRIOR) and lbl not in by:
            by[lbl] = v
    if by:
        return by.get(CURRENT), by.get(PRIOR)
    return (vals[0] if vals else None), (vals[1] if len(vals) > 1 else None)


def period_displays(vals: list[dict]) -> dict[str, str | None]:
    """The printed header text (e.g. "31 December 2023") for whichever periods this row names."""
    out: dict[str, str | None] = {}
    for v in vals:
        lbl = _named(v)
        if lbl in (CURRENT, PRIOR) and lbl not in out:
            out[lbl] = v.get("period_display") or v.get("period_label")
    return out


def slot_for(row: dict, basis: str, period: str) -> dict | None:
    """The one value dict for a (basis, period) — the slot an edit reads and writes.

    ``current``/``prior`` go through :func:`split_current_prior`, so an edit lands on the same
    figure the grid shows even when the extractor labelled the columns positionally.
    """
    vals = basis_values(row, basis)
    if period in (CURRENT, PRIOR):
        cur, prior = split_current_prior(vals)
        return cur if period == CURRENT else prior
    return next((v for v in vals if v.get("period_label") == period), None)


def edited_for(row: dict, basis: str, period: str | None = None) -> bool:
    """Whether this row carries a MANUAL value for the given basis (and period, when named).

    ``edited_slots`` records exactly which (basis, period) figures an analyst typed into, and the
    granularity matters in both directions: an edit to the consolidated column must not claim the
    standalone one, and an edit to THIS year must not claim last year — otherwise correcting one
    figure silently changes the other column of the same row. A run edited before slots were
    recorded only has the row-level flag, so it is honoured for every slot; that stays true to
    what those edits meant when they were made.
    """
    slots = row.get("edited_slots")
    if slots is None:
        return bool(row.get("edited"))
    for s in slots:
        b, _, p = str(s).partition("/")
        if b == basis and (period is None or p == period):
            return True
    return False


def _num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def concept_value(group: list[dict], basis: str, period: str) -> float | None:
    """The figure the app shows for one concept in one (basis, period).

    Several printed lines legitimately map to one concept (three depreciation lines into
    "Depreciation and amortisation", a handful of odds and ends into a section's "Others"), so
    the default is their sum. A MANUAL edit replaces that outright: it is the analyst's answer
    for the line, not one more contributor to add to the printed ones — entering 200 over a
    combined 150 has to show 200, not 350.

    The statement view, the export and the accounting checks all read the figure through here.
    Reading it differently in any of them means a number gets validated that nobody is shown.
    """
    edited = next((r for r in group if edited_for(r, basis, period)), None)
    if edited is not None:
        return _num((slot_for(edited, basis, period) or {}).get("value"))
    total = None
    for r in group:
        n = _num((slot_for(r, basis, period) or {}).get("value"))
        if n is not None:
            total = n if total is None else total + n
    return total

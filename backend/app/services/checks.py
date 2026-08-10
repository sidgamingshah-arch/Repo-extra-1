"""Generic checks-and-balances engine.

Operates on a flat statement row list (the shape served by the API / produced by the
extract stage) and computes the validations whose failure populates the review queue:

* balance identity   — TOTAL ASSETS == TOTAL EQUITY AND LIABILITIES
* subtotal rollups    — a subtotal equals the sum of the item rows since the previous
                        subtotal/section boundary
* sign anomalies      — an expense line carrying a positive value
* note reconciliation — a face value ties to its note total; computed by the reconcile
                        stage (services.reconcile) and turned into checks by
                        ``check_reconciliation`` over the stage's report entries

``run_all`` covers the row-based checks (balance/subtotal/sign); ``check_reconciliation``
takes the reconcile stage's entries because reconciliation needs the note detail, not just
the flat face rows. Pure and unit-tested; used for real uploaded extractions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.services.reconcile import tie_status


@dataclass
class Check:
    id: str
    type: str
    title: str
    status: str            # "fail" | "pass"
    expected: Decimal | None = None
    actual: Decimal | None = None
    delta: Decimal | None = None
    target: str | None = None
    detail: dict = field(default_factory=dict)


def _num(row: dict, period: str = "v1") -> Decimal | None:
    v = row.get(period)
    return None if v is None else Decimal(str(v))


def check_balance(rows: list[dict], period: str = "v1", tol: Decimal = Decimal(1)) -> list[Check]:
    assets = next((r for r in rows if r["id"] == "tot_assets"), None)
    eqliab = next((r for r in rows if r["id"] == "tot_eq"), None)
    if not assets or not eqliab:
        return []
    a, e = _num(assets, period), _num(eqliab, period)
    if a is None or e is None:
        return []
    delta = a - e
    return [Check(
        id="balance", type="balance", title="Balance sheet balances",
        status="pass" if abs(delta) <= tol else "fail",
        expected=e, actual=a, delta=delta, target="tot_assets",
    )]


def check_subtotals(rows: list[dict], period: str = "v1", tol: Decimal = Decimal(1)) -> list[Check]:
    """Each subtotal should equal the sum of item rows since the last boundary."""
    out: list[Check] = []
    running = Decimal(0)
    for r in rows:
        kind = r.get("kind", "item")
        if kind in ("section", "subhead"):
            running = Decimal(0)
        elif kind == "item":
            n = _num(r, period)
            if n is not None:
                running += n
        elif kind == "subtotal":
            reported = _num(r, period)
            if reported is not None:
                delta = reported - running
                out.append(Check(
                    id=f"subtotal:{r['id']}", type="subtotal",
                    title=f"Subtotal rollup — {r['label']}",
                    status="pass" if abs(delta) <= tol else "fail",
                    expected=running, actual=reported, delta=delta, target=r["id"],
                ))
            running = Decimal(0)
        elif kind == "total":
            running = Decimal(0)
    return out


# Line ids / label hints that are expenses (expected negative in P&L convention).
_EXPENSE_HINTS = ("finance cost", "expense", "cost of", "depreciation", "tax")


def check_signs(rows: list[dict], period: str = "v1") -> list[Check]:
    out: list[Check] = []
    for r in rows:
        if r.get("kind") != "item":
            continue
        label = r.get("label", "").lower()
        n = _num(r, period)
        if n is None:
            continue
        is_expense = any(h in label for h in _EXPENSE_HINTS)
        if is_expense and n > 0:
            out.append(Check(
                id=f"sign:{r['id']}", type="sign",
                title=f"Sign anomaly — {r['label']} positive",
                status="fail", actual=n, expected=-n, target=r["id"],
                detail={"expected_sign": "negative"},
            ))
    return out


def check_reconciliation(entries: list[dict], tol: Decimal = Decimal(1)) -> list[Check]:
    """Turn the reconcile stage's report entries into note→face tie checks.

    Only an entry graded ``untied`` is a failure — a corroborated breakdown that does not add
    up. Entries graded ``unconfirmed`` are skipped entirely: the cited note is not a
    decomposition of that face figure (an analysis note, a segment table), so there is nothing
    to assert either way.
    """
    out: list[Check] = []
    for e in entries:
        note = e.get("note_number")
        basis, period = e.get("basis"), e.get("period_label")
        resid = e.get("residual")
        resid_d = None if resid is None else Decimal(str(resid))
        status = tie_status(e)
        if status == "unconfirmed":
            continue
        ok = status == "tied"
        out.append(Check(
            id=f"note_tie:{note}:{basis}:{period}", type="note_tie",
            title=f"Note {note} ties to face ({basis}/{period})",
            status="pass" if ok else "fail",
            expected=(None if e.get("raw_face") is None else Decimal(str(e["raw_face"]))),
            actual=(None if e.get("raw_face") is None or resid_d is None
                    else Decimal(str(e["raw_face"])) - resid_d),
            delta=resid_d, target=f"note:{note}",
            detail={"note_number": note, "basis": basis, "period": period},
        ))
    return out


def run_all(rows: list[dict], period: str = "v1") -> list[Check]:
    return check_balance(rows, period) + check_subtotals(rows, period) + check_signs(rows, period)


def failing(rows: list[dict], period: str = "v1") -> list[Check]:
    return [c for c in run_all(rows, period) if c.status == "fail"]

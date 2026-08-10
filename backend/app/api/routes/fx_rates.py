"""FX rate master — the admin-maintained rates used for presentation currency conversion.

Reading is open to any authenticated caller (the Workspace has to look a rate up before it
will re-currency a statement); creating, updating and deleting is administrator-only under
``config:settings``, the existing configuration permission that already gates the Settings
screen this master is maintained from.

Nothing is seeded. An empty master is the correct initial state — see ``app.services.fx``
for why resolution reports failure instead of quietly converting at 1.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import db
from app.security import Permission, current_principal, require
from app.services.fx import (
    FxError,
    format_rate,
    parse_rate,
    resolve_rate,
    unresolved_payload,
    validate_pair,
)

router = APIRouter(prefix="/fx-rates", tags=["fx-rates"])

# Writes are configuration, not analyst work: one admin-maintained master, so a converted
# figure on anyone's screen traces back to a rate someone accountable entered.
_admin = Depends(require(Permission.CONFIG_SETTINGS))


class FxRateBody(BaseModel):
    """An admin-entered rate: 1 ``base`` = ``rate`` ``quote``, as of ``as_of``.

    ``rate`` is accepted as a string or a number and validated into a Decimal; it is never
    handled as a float, because these values multiply financial figures.
    """

    base: str
    quote: str
    rate: str | float | int
    as_of: date | None = None
    source: str | None = None


def _row_payload(row) -> dict:
    return {
        "id": row.id,
        "base": row.base_ccy,
        "quote": row.quote_ccy,
        "rate": row.rate,
        "as_of": row.as_of.isoformat(),
        "source": row.source or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _clean(body: FxRateBody) -> tuple[str, str, str, date, str]:
    """Validate a submitted rate, or 422 with the message the admin needs to act on."""
    try:
        base, quote = validate_pair(body.base, body.quote)
        rate = format_rate(parse_rate(body.rate))
    except FxError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # No as-of given means "as of today" — the rate still gets a real date, because a
    # conversion caption without one cannot tell the reader how stale the number is.
    as_of = body.as_of or datetime.now(timezone.utc).date()
    return base, quote, rate, as_of, (body.source or "").strip()


@router.get("", dependencies=[Depends(current_principal)])
def list_fx_rates(session: Session = Depends(db)) -> dict:
    """The whole master, newest rate first — read by the admin editor and the Workspace."""
    from app.db.models import FxRate

    rows = session.execute(
        select(FxRate).order_by(FxRate.as_of.desc(), FxRate.base_ccy, FxRate.quote_ccy)
    ).scalars().all()
    return {"rates": [_row_payload(r) for r in rows]}


@router.get("/resolve", dependencies=[Depends(current_principal)])
def resolve_fx_rate(
    base: str = Query(...),
    quote: str = Query(...),
    session: Session = Depends(db),
) -> dict:
    """Resolve one pair. Always 200 for a well-formed pair: ``resolved`` says whether the
    master could answer, so a missing rate is a normal, displayable answer rather than an
    error the UI might swallow and convert anyway."""
    try:
        b, q = validate_pair(base, quote)
    except FxError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    resolved = resolve_rate(session, b, q)
    return resolved.to_payload() if resolved else unresolved_payload(b, q)


@router.post("", status_code=201, dependencies=[_admin])
def upsert_fx_rate(body: FxRateBody, session: Session = Depends(db)) -> dict:
    """Create a rate, or restate the one already held for the same pair + as-of date.

    Upsert rather than a hard conflict: re-entering a day's rate is a correction, and
    forcing the admin to delete first would leave a window where the master has no rate.
    """
    from app.db.models import FxRate

    base, quote, rate, as_of, source = _clean(body)
    row = session.execute(
        select(FxRate).where(
            FxRate.base_ccy == base, FxRate.quote_ccy == quote, FxRate.as_of == as_of
        )
    ).scalars().first()
    if row is None:
        row = FxRate(base_ccy=base, quote_ccy=quote, rate=rate, as_of=as_of, source=source)
        session.add(row)
    else:
        row.rate = rate
        row.source = source
    session.commit()
    return _row_payload(row)


@router.put("/{rate_id}", dependencies=[_admin])
def update_fx_rate(rate_id: str, body: FxRateBody, session: Session = Depends(db)) -> dict:
    """Replace one stored rate in place (the admin editor's row edit)."""
    from app.db.models import FxRate

    row = session.get(FxRate, rate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="FX rate not found")

    base, quote, rate, as_of, source = _clean(body)
    row.base_ccy, row.quote_ccy, row.rate, row.as_of, row.source = base, quote, rate, as_of, source
    try:
        session.commit()
    except IntegrityError as exc:
        # Edited onto a (pair, as-of) that already exists — reject rather than let two rows
        # compete to be the current rate for the same day.
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"A rate for {base}->{quote} as of {as_of.isoformat()} already exists",
        ) from exc
    return _row_payload(row)


@router.delete("/{rate_id}", status_code=204, dependencies=[_admin])
def delete_fx_rate(rate_id: str, session: Session = Depends(db)) -> Response:
    from app.db.models import FxRate

    row = session.get(FxRate, rate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="FX rate not found")
    session.delete(row)
    session.commit()
    return Response(status_code=204)

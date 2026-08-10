"""FX rate master: validation + honest resolution of a base→quote rate.

The master is admin-maintained (``app.db.models.FxRate``); there is no rate feed and
nothing is seeded. Resolution therefore has exactly two outcomes an analyst can trust:

* ``direct``  — an administrator entered this very pair. Used verbatim.
* ``inverse`` — only the opposite pair exists, so the reciprocal is used and the result
  is flagged ``derived`` with its path, because 1/rate is *our* arithmetic and not the
  rate anybody published (bid/ask spreads make the true inverse differ slightly).

Triangulating through a third currency is deliberately NOT attempted: chaining two
independently-dated rates manufactures a number nobody quoted, and the compounded
staleness is invisible in the result. When neither branch matches, resolution fails and
says why — the caller must refuse to convert rather than present source figures under a
target-currency label.

All arithmetic is Decimal: the rates multiply financial figures, so float drift here
would surface as wrong money.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session

CCY_RE = re.compile(r"^[A-Z]{3}$")

# Reciprocals are irrational in decimal (1/3, 1/7 …). 20 significant digits keeps the
# round-trip error far below any presentational rounding while staying a finite string.
_INVERSE_PRECISION = 20


class FxError(ValueError):
    """A rejected rate/pair — carries the message shown to the admin who typed it."""


def normalize_ccy(value: str | None, *, field: str) -> str:
    """Uppercase + validate an ISO-4217-shaped code, or raise ``FxError``."""
    code = (value or "").strip().upper()
    if not CCY_RE.match(code):
        raise FxError(f"{field} must be a 3-letter currency code (e.g. USD), got {value!r}")
    return code


def parse_rate(value) -> Decimal:
    """Parse a rate into a positive Decimal, or raise ``FxError``.

    Zero and negatives are rejected outright: a non-positive multiplier cannot be a price
    of one currency in another, and letting one through would silently zero out or flip
    the sign of every converted figure.
    """
    try:
        rate = Decimal(str(value).strip())
    except (InvalidOperation, ArithmeticError) as exc:
        raise FxError(f"rate must be a number, got {value!r}") from exc
    if not rate.is_finite():
        raise FxError(f"rate must be a finite number, got {value!r}")
    if rate <= 0:
        raise FxError(f"rate must be greater than 0, got {value!r}")
    return rate


def validate_pair(base: str | None, quote: str | None) -> tuple[str, str]:
    """Validate + normalize a currency pair (codes well-formed, and genuinely a pair)."""
    b = normalize_ccy(base, field="base currency")
    q = normalize_ccy(quote, field="quote currency")
    if b == q:
        raise FxError(f"base and quote currency must differ (both {b})")
    return b, q


def format_rate(rate: Decimal) -> str:
    """Canonical text form for storage/transport — no exponent, no trailing zero noise."""
    normalized = rate.normalize()
    # ``normalize`` turns 100 into 1E+2; expand it back so the stored text stays readable
    # and parses identically on the way out.
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


@dataclass(frozen=True)
class ResolvedRate:
    """A rate the API is willing to stand behind, with how it was obtained."""

    base: str
    quote: str
    rate: Decimal
    as_of: date
    # False only for a rate an administrator entered for exactly this direction.
    derived: bool
    method: str          # "direct" | "inverse"
    path: list[str]      # the currencies actually traversed, in master order
    source: str
    rate_id: str

    def to_payload(self) -> dict:
        return {
            "resolved": True,
            "base": self.base,
            "quote": self.quote,
            "rate": format_rate(self.rate),
            "as_of": self.as_of.isoformat(),
            "derived": self.derived,
            "method": self.method,
            "path": list(self.path),
            "source": self.source,
            "rate_id": self.rate_id,
        }


def _latest(session: Session, base: str, quote: str):
    """The most recently dated master row for a direction, or None.

    Newest ``as_of`` wins (``created_at`` breaks a same-day tie), so re-stating a pair
    supersedes the older quote instead of the resolver picking an arbitrary row.
    """
    from app.db.models import FxRate

    return session.execute(
        select(FxRate)
        .where(FxRate.base_ccy == base, FxRate.quote_ccy == quote)
        .order_by(FxRate.as_of.desc(), FxRate.created_at.desc())
    ).scalars().first()


def resolve_rate(session: Session, base: str, quote: str) -> ResolvedRate | None:
    """Resolve base→quote from the master, or None when the master cannot answer.

    ``None`` means "no rate configured" — never a fallback of 1, which would present
    source-currency figures under a target-currency heading.
    """
    direct = _latest(session, base, quote)
    if direct is not None:
        return ResolvedRate(
            base=base, quote=quote, rate=Decimal(direct.rate), as_of=direct.as_of,
            derived=False, method="direct", path=[base, quote],
            source=direct.source or "", rate_id=direct.id,
        )

    opposite = _latest(session, quote, base)
    if opposite is not None:
        stored = Decimal(opposite.rate)
        try:
            with localcontext() as ctx:
                ctx.prec = _INVERSE_PRECISION
                inverse = Decimal(1) / stored
        except (DivisionByZero, InvalidOperation):  # pragma: no cover - parse_rate blocks 0
            return None
        # ``path`` names the row we actually read (quote→base), so the caller can say
        # *which* stored rate was inverted rather than implying we hold this direction.
        return ResolvedRate(
            base=base, quote=quote, rate=inverse, as_of=opposite.as_of,
            derived=True, method="inverse", path=[quote, base],
            source=opposite.source or "", rate_id=opposite.id,
        )

    return None


def unresolved_payload(base: str, quote: str) -> dict:
    """The negative answer, shaped like the positive one so clients branch on one field."""
    return {
        "resolved": False,
        "base": base,
        "quote": quote,
        "reason": "no_rate_configured",
        "detail": (
            f"No FX rate configured for {base}->{quote} (nor {quote}->{base} to invert). "
            "An administrator must add it to the FX rate master."
        ),
    }

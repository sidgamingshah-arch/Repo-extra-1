"""What "a line" means to the review header's third tile — ONE definition, both paths.

The tile reads ``summary.passed`` and its label is the same sentence on both screens: "lines with no
finding". Two routes serve it — the real extraction (:mod:`app.api.routes.documents`) and the seeded
sample (:mod:`app.api.routes.projects`) — and they were counting two different POPULATIONS under
that one label:

* real: every serialized line item, subtotal and total rows included;
* sample: only rows whose display ``kind`` is ``"item"``, so the seeded project served 31 over its 33
  item rows while the same statements also served 6 subtotal and 4 total rows — 8 of which no finding
  named. The label was understating the quantity it names by 8.

A SUBTOTAL AND A TOTAL ARE LINES. The balance card names ``bs_total_assets``; a section
reconciliation names its subtotal; a guard names whatever line it broke on. Those are exactly the
lines findings are most often ABOUT, so excluding them from the population makes "lines with no
finding" a claim about a set the reader cannot see. What is NOT a line is a caption that carries no
figure — a section heading or a spacer — and each path spells that in its own vocabulary: the real
path serves the extracted ``role``, the sample its display ``kind``. Both spellings live here, in one
predicate, instead of in two counters that drift.
"""
from __future__ import annotations

from collections.abc import Iterable

# The extracted roles (core/models/enums.py::LineRole) and the sample's display kinds that are
# CAPTIONS: they carry no figure, so no finding can be about them and they are in no population a
# reader counts. Everything else — line, subtotal, total, item — is a line.
_CAPTIONS = frozenset({"header", "spacer", "section", "subhead"})


def is_statement_line(row: dict) -> bool:
    """True when ``row`` is one of the lines the review header counts.

    Reads whichever of ``role`` (real extraction) or ``kind`` (sample display rows) the row carries;
    a row carrying neither is a line, because the two producers always say when a row is a caption
    and never say when it is not.
    """
    for field in ("role", "kind"):
        if str(row.get(field) or "").lower() in _CAPTIONS:
            return False
    return True


def lines_with_no_finding(rows: Iterable[dict], indicted) -> int:
    """How many statement lines no served finding names.

    ``indicted`` is a membership test over the SAME rows this iterates, which is why it is passed in
    rather than derived here: the real path identifies an indicted row by its POSITION (an unmapped
    row has no key and two rows can print one caption) while the sample identifies it by row id, and
    inventing a third way of asking "does a finding name this row" is how the two counts diverged in
    the first place. Counting per row rather than subtracting two totals also means a caption that
    somehow attracted a finding cannot push the answer below zero.
    """
    return sum(1 for i, r in enumerate(rows) if is_statement_line(r) and not indicted(i, r))

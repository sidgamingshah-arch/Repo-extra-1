"""Sign & unit normalization stage — and what the rulebook expects the fact to be.

Produces the sign-normalized ``ExtractedValue.value`` from the printed ``value_raw`` using
signals the printed magnitude alone doesn't carry:

* ``Less:`` / ``Add:`` label cues — a line prefixed "Less:" is a deduction (negative);
  "Add:" is an addition (positive).
* the ontology's ``sign_rule.flip_if_label_matches`` regexes for the mapped concept — the
  ontology author's targeted sign corrections.

The printed-sign tier (parentheses / trailing minus) is already decoded into ``value_raw``
by ``services.numbers`` at extraction; this stage layers the label-driven corrections on top.
Values with no applicable cue keep ``value == value_raw``.

WHERE PARENTHESES ARE DECIDED, and why the global switch is reported rather than honoured.
``parse_number`` reads the LOCALE's ``number_format.negative`` (``["paren", "minus"]``), which is
the live switch and the right altitude for it: parentheses-as-negative is a convention of how a
filing is printed. ``global_rules.paren_means_negative`` is a second copy of the same switch that
the parser never sees, and it cannot be honoured after the fact — only the signed magnitude
survives extraction, so nothing downstream could tell "(600)" from "-600" in order to undo one
and not the other. The duplicate switch that pretended otherwise has been removed from
``GlobalRules``: parentheses are decided by ``number_format_by_locale`` alone, at the one point
where the printed text is still in hand.

Once a value is normalised, two v2 declarations say what the resulting FACT is supposed to look
like, and both are checked here because this is the stage that finishes the number:

* ``sign_convention`` (``positive_expected`` / ``negative_expected`` / ``either``) is an
  EXPECTATION, not a transformation — the rulebook says so in as many words: "a concept whose
  sign_convention is positive_expected or negative_expected but whose loaded value carries the
  opposite sign is a review trigger, not an auto-correction". So a figure arriving with the wrong
  sign is flagged and its sign confidence drops; the value is left exactly as reported.
  ``sign_rule`` keeps doing the normalising — the two are different jobs on purpose, since a
  concept can legitimately want a targeted flip AND an expected sign.

* ``temporality`` (instant / duration) and ``unit_of_account`` (balance / flow / subtotal) say
  whether the concept is a position at a date or a movement over a period. The balance-sheet
  non-controlling-interests BALANCE and the profit-attribution FLOW share their caption exactly,
  and the filing prints them in different statements; a caption match alone will happily file the
  P&L figure on the balance sheet, where it is individually plausible and every subtotal still
  ties. The two are different facts, so the figure is NOT merged into the concept: the row keeps
  its value and provenance and loses the concept, which puts it in the review queue instead of on
  the balance sheet. The statement each temporality belongs to is read from the rulebook too — an
  ontology that declares its balance-sheet sections ``duration`` gets no such finding.
"""
from __future__ import annotations

import re
from decimal import Decimal

from app.core.models import DocumentModel
from app.core.models.line_item import UnitContext
from app.core.stage import PipelineContext

_LESS = re.compile(r"^\s*(less|deduct)\b|less:", re.IGNORECASE)
_ADD = re.compile(r"^\s*add\b|add:", re.IGNORECASE)

# "Amounts in ₹ crore", "(RMB'000)", "in thousands of USD", "figures in HK$ million" …
_UNIT_SCALE = {"thousand": Decimal(1_000), "lakh": Decimal(100_000), "lac": Decimal(100_000),
               "ten thousand": Decimal(10_000),
               "million": Decimal(1_000_000), "mn": Decimal(1_000_000),
               "hundred million": Decimal(100_000_000),
               "crore": Decimal(10_000_000), "cr": Decimal(10_000_000),
               "billion": Decimal(1_000_000_000), "bn": Decimal(1_000_000_000)}
# Most real filings never spell the scale out: the statement column head simply reads
# "RMB'000" / "HK$’000" / "人民幣千元". Those idioms ARE the declaration, so they are matched
# alongside the spelled-out words — including the curly apostrophe, which is what a PDF text
# layer almost always yields. Patterns are tried in order at the leftmost match, so the longer
# idiom wins where two overlap ('000,000 over '000, 百萬 over 萬).
_SCALE_PATTERNS = [
    (re.compile(r"(?<![\d.])['’`]0{3}[,.]0{3}"), "million"),        # RMB'000,000
    (re.compile(r"(?<![\d.])['’`]0{3}"), "thousand"),               # RMB'000, HK$’000, ₹'000
    (re.compile(r"百萬|百万"), "million"),
    (re.compile(r"千元"), "thousand"),        # 人民幣千元 — bare 千 is too weak to trust
    (re.compile(r"億|亿"), "hundred million"),
    (re.compile(r"萬|万"), "ten thousand"),
    (re.compile(r"\b(thousands?|lakhs?|lacs?|millions?|mn|crores?|cr|billions?|bn)\b",
                re.IGNORECASE), None),                              # label taken from the match
]
_CCY = [("₹", "INR"), ("rs.", "INR"), ("inr", "INR"),
        ("hk$", "HKD"), ("hkd", "HKD"), ("港幣", "HKD"), ("港币", "HKD"), ("港元", "HKD"),
        ("rmb", "CNY"), ("cny", "CNY"), ("人民幣", "CNY"), ("人民币", "CNY"),
        ("us$", "USD"), ("usd", "USD"),
        ("新台幣", "TWD"), ("新台币", "TWD"), ("日圓", "JPY"), ("日元", "JPY"),
        ("$", "USD"), ("€", "EUR"), ("eur", "EUR"), ("£", "GBP"), ("gbp", "GBP")]
# A statement-face count high enough to cover every face of a group annual report, but bounded
# so a mis-classified 270-page document can't turn detection into a full-text scan.
_MAX_FACE_SCAN = 12


def _scan_scale(text: str) -> str | None:
    """The scale label declared in `text`, preferring the earliest declaration in reading order."""
    best: tuple[int, str] | None = None
    for rx, label in _SCALE_PATTERNS:
        m = rx.search(text)
        if m is None:
            continue
        word = (label or m.group(1).rstrip("s")).lower()
        if best is None or m.start() < best[0]:
            best = (m.start(), word)
    return best[1] if best else None


def _detect_units(ctx: PipelineContext, fmt: str, doc: DocumentModel | None = None
                  ) -> UnitContext | None:
    """Detect a source scale + currency from a units declaration (e.g. "Amounts in ₹ crore").
    Returns None when nothing is declared — the caller then treats values as reported rather
    than guessing a scale.

    In an annual report the declaration lives on the *statement* pages (p.100+), not the cover,
    so the front matter is scanned first (a cover banner still wins when present) and then each
    statement face. A chunk only ends the search once it yields a scale: a stray currency
    mention in the front matter must not pre-empt the real "RMB'000" column head further in."""
    from app.services.derived import document_text

    try:
        pages = document_text(ctx.raw_bytes or b"", fmt)
    except Exception:  # noqa: BLE001
        return None
    by_index = dict(pages)
    # (page index for provenance, text) chunks in scan order; front matter is one chunk so a
    # scale and currency split across the first two pages still combine, as they always have.
    chunks: list[tuple[int | None, str]] = [(None, " ".join(t for _, t in pages[:2]))]
    for page in (doc.face_pages() if doc is not None else [])[:_MAX_FACE_SCAN]:
        chunks.append((page.index, by_index.get(page.index, "")))

    currency: str | None = None
    for index, raw in chunks:
        text = raw.lower()
        if not text:
            continue
        # Remember the first currency seen: the face page declaring the scale may print only
        # "'000" with the currency stated once, elsewhere.
        currency = currency or next((code for tok, code in _CCY if tok in text), None)
        scale_word = _scan_scale(text)
        if scale_word is None:
            continue
        return UnitContext(currency=currency or "", units_label=scale_word,
                           scale_factor=_UNIT_SCALE.get(scale_word, Decimal(1)),
                           source_bbox_page=index)
    if currency is None:
        return None
    # Currency without a scale: record it, but keep scale 1 — figures are as reported.
    return UnitContext(currency=currency, scale_factor=Decimal(1), units_label=None)


_SIGN_EXPECTED = ("positive_expected", "negative_expected")


def _statement_shape(ontology) -> dict[str, tuple[str | None, frozenset[str]]]:
    """Per statement, the ``temporality`` and the units of account its concepts declare.

    Derived from the rulebook rather than stated here, because "the balance sheet is instant" is a
    fact about the rulebook's sections, not about this module: a v1 definition declares neither and
    gets no expectation at all, and one that changed its mind would change the finding.

    Only a UNANIMOUS temporality is used. A statement whose concepts disagree cannot say anything
    about a row printed on it, and guessing from a majority would flag the minority as wrong.
    ``subtotal`` is left out of the unit set — a subtotal is neither a balance nor a flow, so it
    would otherwise look foreign on every statement it appears on.
    """
    temporal: dict[str, set[str]] = {}
    units: dict[str, set[str]] = {}
    for m in getattr(ontology, "mappings", []) or []:
        statement = getattr(m.statement, "value", None) or m.statement
        if not statement:
            continue
        if m.temporality:
            temporal.setdefault(statement, set()).add(m.temporality)
        if m.unit_of_account and m.unit_of_account != "subtotal":
            units.setdefault(statement, set()).add(m.unit_of_account)
    return {st: (next(iter(temporal[st])) if len(temporal.get(st, ())) == 1 else None,
                 frozenset(units.get(st, ())))
            for st in set(temporal) | set(units)}


class NormalizeStage:
    name = "normalize"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        # Source units/currency ("Amounts in ₹ crore") — recorded so the UI/export can convert
        # to a chosen presentation unit knowing the base (and never guessing when undeclared).
        detected = _detect_units(ctx, doc.fmt.value, doc)
        if detected is not None:
            doc.unit_context = detected
            ctx.log(f"normalize:units={detected.units_label or 'as_reported'}"
                    f"/{detected.currency or 'unknown_ccy'}")

        ontology = getattr(ctx, "ontology", None)
        sign_by_key: dict[str, list] = {}
        expected_sign: dict[str, str] = {}
        temporality: dict[str, str] = {}
        unit_of_account: dict[str, str] = {}
        if ontology is not None:
            for m in getattr(ontology, "mappings", []) or []:
                pats = getattr(getattr(m, "sign_rule", None), "flip_if_label_matches", None) or []
                if pats:
                    sign_by_key[m.canonical_key] = [re.compile(p, re.IGNORECASE) for p in pats]
                if m.sign_convention in _SIGN_EXPECTED:
                    expected_sign[m.canonical_key] = m.sign_convention
                if m.temporality:
                    temporality[m.canonical_key] = m.temporality
                if m.unit_of_account:
                    unit_of_account[m.canonical_key] = m.unit_of_account

        changed = 0
        for li in doc.line_items:
            label = li.source_label or ""
            less = bool(_LESS.search(label))
            add = bool(_ADD.search(label))
            flips = sign_by_key.get(li.canonical_key or "", [])
            flip = any(rx.search(label) for rx in flips)
            if not (less or add or flip):
                continue
            for ev in li.values.values():
                raw = ev.value_raw
                if raw is None:
                    continue
                v = raw
                if less:
                    v = -abs(raw)
                elif add:
                    v = abs(raw)
                if flip:
                    v = -v
                if v != ev.value:
                    ev.value = v
                    changed += 1

        ctx.log(f"normalize:sign_adjusted={changed}")
        self._check_expectations(doc, ctx, ontology, expected_sign, temporality, unit_of_account)
        return doc


    @staticmethod
    def _check_expectations(doc: DocumentModel, ctx: PipelineContext, ontology,
                            expected_sign: dict[str, str], temporality: dict[str, str],
                            unit_of_account: dict[str, str]) -> None:
        """Compare each finished figure with what its concept says it should be.

        Nothing here changes a number. The sign check records a finding; the balance-versus-flow
        check unfiles the row, which removes a WRONG figure rather than producing one — the value,
        the label and the provenance all stay on the row for the reviewer who has to place it.
        """
        if ontology is None:
            return
        shape = _statement_shape(ontology)
        stmt_by_page = {p.index: p.statement for p in doc.pages if p.statement}
        wrong_sign = confused = 0
        for li in doc.line_items:
            key = li.canonical_key
            if not key:
                continue

            want = expected_sign.get(key)
            if want:
                for ev in li.values.values():
                    val = ev.value if ev.value is not None else ev.value_raw
                    if val is None or val == 0:
                        continue
                    if (want == "positive_expected" and val > 0) or (
                            want == "negative_expected" and val < 0):
                        continue
                    # Flagged, never flipped: the opposite sign usually means the row is on the
                    # wrong concept, and flipping it would hide that behind a plausible figure
                    # while the template's subtotal identities quietly stopped meaning anything.
                    ev.confidence.sign = min(ev.confidence.sign, 0.35)
                    ev.confidence.flags.append(f"sign_opposite_to_expected:{want}")
                    flag = f"sign_opposite_to_expected:{key}"
                    if flag not in li.confidence.flags:
                        li.confidence.flags.append(flag)
                    wrong_sign += 1

            statement = next((stmt_by_page.get(ev.provenance.page_index)
                              for ev in li.values.values() if ev.provenance is not None), None)
            expect = shape.get(statement or "")
            if expect is None:
                continue
            want_temporality, want_units = expect
            got_temporality = temporality.get(key)
            got_unit = unit_of_account.get(key)
            reasons = []
            if want_temporality and got_temporality and got_temporality != want_temporality:
                reasons.append(f"temporality:{got_temporality}!={want_temporality}")
            # A subtotal is neither a balance nor a flow, so it is not compared on units.
            if want_units and got_unit and got_unit != "subtotal" and got_unit not in want_units:
                reasons.append(f"unit_of_account:{got_unit}!={'/'.join(sorted(want_units))}")
            if not reasons:
                continue
            li.canonical_key = None
            li.confidence.mapping = min(li.confidence.mapping or 0.3, 0.3)
            li.confidence.flags.append(f"balance_flow_confusion:{key}:{','.join(reasons)}")
            li.confidence.flags.append("low_mapping_confidence")
            confused += 1
            ctx.log(f"normalize:balance_flow_confusion {key} on {statement}"
                    f" ({';'.join(reasons)}) row={li.source_label!r}")
        if wrong_sign or confused:
            ctx.log(f"normalize:sign_unexpected={wrong_sign} balance_flow_confusion={confused}")

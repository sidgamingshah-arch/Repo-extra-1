"""Words → line items, shared by the native-PDF and OCR paths.

Both the native text layer (PyMuPDF words) and the scanned path (OCR words) produce the
same thing: positioned words with a normalized bounding box. This module groups them into
rows, separates label / note-ref / value columns, and emits ``LineItem``s whose
``ExtractedValue.provenance`` carries the page + normalized bbox — so click-to-source works
identically whether the value came from a text layer or from OCR. Values are read here
(deterministically); semantic mapping to canonical concepts happens later.

Two layouts are handled. Most statement faces are *two-column comparatives* (current / prior,
optionally × consolidated / standalone). A statement of changes in equity is a *matrix*: its
columns are equity components (share capital, share premium, each reserve, retained profits,
total, non-controlling interests, total equity) and its rows are movements. Reading a matrix
with the two-column reconstruction produces nonsense — the columns are attributed to periods
that do not exist and the movement date is read as a value — so it gets its own path
(``_detect_matrix`` … ``_matrix_items``) that names every column from the header band.
"""
from __future__ import annotations

import json
import re
import statistics
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from app.core.models.enums import Basis, LineRole, ValueSource
from app.core.models.geometry import BBox, Provenance
from app.core.models.line_item import ExtractedValue, LineItem, NoteRef, UnitContext
from app.schemas.ontology import Normalisation, ScopeSelection
from app.services.han import to_simplified
# The section vocabulary is a property of how statements are PRINTED, not of any ontology, so
# reading a banner here uses the same function mapping does rather than a second copy of it.
from app.services.mapping import section_of_banner

_NUM = re.compile(r"^\(?-?[\d,]*\.?\d+\)?%?$")
_NOTE = re.compile(r"^note[s]?\.?$", re.IGNORECASE)
# A column header for the note-reference column (English + Chinese). Real statements print it
# once at the top; the cells beneath it hold bare note numbers, not monetary values.
_NOTE_HDR = re.compile(r"^(notes?|附註|附注)$", re.IGNORECASE)


def _is_note_number(t: str) -> bool:
    """A bare 1–2 digit integer — the shape of a note reference (never a formatted amount).

    A row often cites several notes ("14, 16(b)", "8, 13"), so the token carries the separator
    that followed it; it is still a note reference, not an amount.
    """
    return re.fullmatch(r"\d{1,2}", t.strip().strip(".,;")) is not None


def _is_money_like(t: str, fmt=None) -> bool:
    """A numeric token that is NOT a bare note number (has a separator/decimal/sign, or ≥3 digits
    — i.e. a real amount). Used to confirm a leading small integer is a note ref, not a value."""
    return _num(t, fmt) is not None and not _is_note_number(t)


# A running-header / statement-title / period-caption label. These carry the entity or the
# statement name + a period date, not a financial line — and the only "number" on them is a
# date fragment (a year or a day-of-month).
_RUNNING_HDR = re.compile(r"annual report|interim report|年報|年度報告|中期報告", re.IGNORECASE)
_HDR_LABEL = re.compile(
    r"statement of|year ended|for the (year|period)|as at\b|as of\b|period ended|"
    r"截至|止年度|財務狀況|现金流量|現金流量|權益變動|权益变动|全面收益|損益及其他|损益及其他|"
    r"綜合.{0,8}表|综合.{0,8}表",
    re.IGNORECASE)


def _is_date_ish(d) -> bool:
    """A value that is really a date fragment: a year (1990–2099) or a day-of-month (1–31),
    with no fractional part (so a real figure like 0.45 or 12,345 never qualifies)."""
    try:
        iv = int(d)
    except (TypeError, ValueError):
        return False
    if iv != d:
        return False
    a = abs(iv)
    return 1 <= a <= 31 or 1990 <= a <= 2099


# A period caption written in CJK numerals — "二零二三年" (2023), "二零二二年" (2022) — is how
# HK/PRC filings head their comparative columns. Also the plain Arabic-numeral year.
_PERIOD_TOKEN = re.compile(r"[〇零一二三四五六七八九十]{2,6}年|\b(19|20)\d{2}\b|"
                           r"[〇零一二三四五六七八九十]{1,2}月|[〇零一二三四五六七八九十]{1,3}日")


def _is_period_only_label(label: str) -> bool:
    """True when the label is nothing but period captions (a column-header row).

    "二零二三年 二零二二年" heads the comparative columns; it is not a line item, whatever
    numbers happen to land on its baseline. Requires that removing the period tokens leaves
    no substantive word, so "Profit for the year ended 2023" is never mistaken for a header.
    """
    if not label or not label.strip():
        return False
    rest = _PERIOD_TOKEN.sub(" ", label)
    rest = re.sub(r"[\s\-–—/、,，.。()（）:：'\u2019\"]+", " ", rest).strip()
    return not rest


def _is_heading_with_note_only(label: str, vals: list) -> bool:
    """A section heading whose only "value" is a note reference that drifted into the row.

    Statement sections ("EQUITY HOLDERS OF THE PARENT", "NON-CURRENT ASSETS") carry no amount;
    when the sole number on the line is note-sized, it is the note column, not a figure.
    Restricted to labels with no lower-case letters so a real caption keeps its value.
    """
    if not vals or not label:
        return False
    letters = [c for c in label if c.isalpha() and c.isascii()]
    if not letters or any(c.islower() for c in letters):
        return False
    return all(_is_date_ish(v) for v in vals)


def _is_noise_row(label: str, vals: list,
                  steps: tuple[tuple[str, object], ...] = ()) -> bool:
    """A title / running-header / period-caption line that leaked in as a row. Dropped only when
    the label is header-like AND every extracted value is a date fragment — so a genuine line that
    merely mentions a statement name (its value being a real amount) is never removed.

    The caption is normalised with the rulebook's pipeline first, which is what makes the
    DECORATED forms of a column-header row recognisable: "2024 RMB'000" and
    "二零二三年（未經審核）" print a year as their only "value", but the inline unit annotation and
    the audit-status note left them looking like captions, so each was emitted as a line item
    whose amount was a year.
    """
    if _RUNNING_HDR.search(label):
        return True
    norm = apply_pipeline(label, steps)
    if _is_period_only_label(norm or label):
        return True
    # Nothing but annotations: after the declared strips the row has no caption at all, and its
    # only figures are date fragments — a units/period header line, not a financial line.
    if not norm and bool(vals) and all(_is_date_ish(v) for v in vals):
        return True
    if _is_heading_with_note_only(label, vals):
        return True
    return bool(vals) and bool(_HDR_LABEL.search(label)) and all(_is_date_ish(v) for v in vals)


@dataclass
class Word:
    text: str
    bbox: BBox   # normalized [0,1] in READING space — what row/column logic uses
    # Where the word actually sits on the rendered page, when that differs from reading space
    # (a page whose text runs sideways — see ``services.pdf_extract._reading_space``). Provenance
    # and therefore click-to-source must use THIS box: the viewer highlights the page as drawn,
    # so a reading-space box would land the highlight in the wrong place.
    page_bbox: BBox | None = None

    @property
    def source_bbox(self) -> BBox:
        return self.page_bbox or self.bbox


def _num(t: str, fmt=None) -> Decimal | None:
    """Parse a token to a Decimal. With no ``fmt`` this uses the fast US-format path (comma
    thousands, dot decimal) — unchanged behaviour. When a locale ``NumberFormat`` is supplied
    it delegates to ``services.numbers.parse_number`` so EU decimal-comma (``1.234,56``),
    Indian grouping (``1,23,456``) and Arabic-Indic digits parse correctly (Req 12)."""
    if fmt is not None:
        from app.services.numbers import parse_number

        p = parse_number(t, fmt)
        return p.value_raw if p.ok else None
    if not _NUM.match(t.strip()):
        return None
    s = t.strip().replace(",", "").replace("%", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        d = Decimal(s)
        return -d if neg else d
    except InvalidOperation:
        return None


def _group_rows(words: list[Word], y_tol: float = 0.012) -> list[list[Word]]:
    """Cluster words into visual rows by vertical position, then order left→right."""
    ordered = sorted(words, key=lambda w: (w.bbox.y0, w.bbox.x0))
    rows: list[list[Word]] = []
    for w in ordered:
        yc = (w.bbox.y0 + w.bbox.y1) / 2
        placed = False
        for row in rows:
            ryc = sum((x.bbox.y0 + x.bbox.y1) / 2 for x in row) / len(row)
            if abs(yc - ryc) <= y_tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w.bbox.x0)
    rows.sort(key=lambda r: min(w.bbox.y0 for w in r))
    return rows


def _scan_row(row: list[Word], fmt=None) -> tuple[list[Word], str | None, list[Word]]:
    """Split one visual row into (label words, note-ref, value words).

    A "Note"/"Notes" token plus the *single* following number is a note reference, not a
    value — the value lives in the far-right column, so it must not be consumed as a value.
    """
    label_words: list[Word] = []
    note_ref: str | None = None
    value_words: list[Word] = []
    i = 0
    while i < len(row):
        tok = row[i].text.strip()
        if _NOTE.match(tok):
            if i + 1 < len(row) and _num(row[i + 1].text, fmt) is not None:
                note_ref = row[i + 1].text.strip().strip(".")
                i += 2
                continue
        if _num(tok, fmt) is not None:
            value_words.append(row[i])
        elif not value_words:   # text before any number is part of the label
            label_words.append(row[i])
        i += 1
    return label_words, note_ref, value_words


def _row_box(row: list[Word]) -> BBox:
    b = row[0].bbox
    for w in row[1:]:
        b = b.union(w.bbox)
    return b


def _looks_like_header(label_words: list[Word],
                       steps: tuple[tuple[str, object], ...] = ()) -> bool:
    """A section header (e.g. "Non-current assets", "ASSETS") is a standalone label line,
    NOT a wrapped continuation — never fold it into a neighbouring valued row.

    The caption is put through the rulebook's normalisation first (minus the case fold, which
    would erase the ALL-CAPS shape being tested) so the printed decorations do not hide the
    shape: a footnote-marked banner ("ASSETS*"), a caption carrying a zero-width space, and a
    CJK sub-heading ending in the FULLWIDTH colon ("其他全面收益：") are all headers, and the
    last of those used to be read as a wrapped continuation and glued onto the row below it.
    """
    text = apply_pipeline(" ".join(w.text for w in label_words), steps,
                          exclude=("case_fold", "trailing_colon"))
    if not text:
        return True
    if text.rstrip(":").isupper():          # ALL-CAPS banners
        return True
    if text.endswith(":"):                  # "Represented by:" style headers
        return True
    return False


# Words that cannot END a finished caption ("TOTAL ASSETS LESS CURRENT …") or that can only
# CONTINUE one ("… AND CASH EQUIVALENTS", "… FOR THE YEAR"). Their presence is what separates a
# wrapped ALL-CAPS label from a genuine ALL-CAPS section banner ("ASSETS", "EQUITY").
# Bare adjectives and connectives cannot end a finished caption, so a line ending in one is a
# wrapped head. "TOTAL COMPREHENSIVE" / "LOSS FOR THE YEAR" is the case that matters most: losing
# the head leaves the tail to be mapped as the profit-or-loss bottom line it is not.
_HEAD_INCOMPLETE = re.compile(
    r"\b(less|in|and|or|of|for|to|from|with|net|total|other|that|which|current|non"
    r"|comprehensive|gross|accumulated|retained|attributable)\s*$",
    re.IGNORECASE)
_CONT_STARTS = re.compile(r"^\s*(and|or|of|for|to|in|from|with|that|which|upon)\b",
                          re.IGNORECASE)
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def _CJK_ONLY(text: str) -> bool:  # noqa: N802 - reads as a predicate at call sites
    """Text that carries Han characters and no Latin words — a translation line."""
    return bool(_HAN.search(text)) and not re.search(r"[A-Za-z]{2,}", text)


def _is_wrapped_head(head: list[Word], cont: list[Word]) -> bool:
    """Whether an ALL-CAPS label-only line is the first line of a WRAPPED caption.

    Statement faces print both: banners that head a group ("ASSETS", "NON-CURRENT
    LIABILITIES") and long captions that wrap ("TOTAL ASSETS LESS CURRENT" / "LIABILITIES",
    "NET DECREASE IN CASH" / "AND CASH EQUIVALENTS"). Treating every ALL-CAPS line as a banner
    discards the head and leaves the valued row labelled with a meaningless tail — which then
    maps to whatever concept that tail resembles. Grammar tells them apart: a wrapped head ends
    mid-phrase, or its continuation begins with a connective.
    """
    head_text = " ".join(w.text for w in head).strip()
    cont_text = " ".join(w.text for w in cont).strip()
    if not head_text or not cont_text:
        return False
    # A bilingual filing prints the translation of the SAME caption on the next line. A
    # CJK-only continuation is therefore never a new banner — and without this the Chinese
    # line breaks the chain between an English wrap and the row carrying the figures.
    if _CJK_ONLY(cont_text):
        return True
    # In a bilingual filing the translation is appended to the SAME row, so the head's last
    # English word is not the row's last word. Grammar is judged on the Latin portion only.
    head_latin = re.sub(r"\s+", " ", _HAN.sub(" ", head_text)).strip()
    return bool(_HEAD_INCOMPLETE.search(head_latin)) or bool(_CONT_STARTS.match(cont_text))


_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")


def _script_of(text: str) -> str | None:
    """Which script a token is written in, or None for digits/punctuation that belong to
    whichever script surrounds them."""
    if _HAN.search(text):
        return "han"
    if _ARABIC.search(text):
        return "arabic"
    if _LATIN.search(text):
        return "latin"
    return None


def _label_lines(words: list[Word]) -> list[list[Word]]:
    """A label's words split back into the physical lines they were printed on.

    A merged caption arrives as line-one's words followed by line-two's, so consecutive words
    with the same vertical centre are one printed line.
    """
    if not words:
        return []
    heights = sorted(max(w.bbox.y1 - w.bbox.y0, 1e-6) for w in words)
    tol = heights[len(heights) // 2] * 0.6
    lines: list[list[Word]] = []
    cur = [words[0]]
    ref = (words[0].bbox.y0 + words[0].bbox.y1) / 2
    for w in words[1:]:
        yc = (w.bbox.y0 + w.bbox.y1) / 2
        if abs(yc - ref) <= tol:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
            ref = yc
    lines.append(cur)
    return lines


def _regroup_scripts(words: list[Word]) -> list[Word]:
    """Keep each language contiguous in a caption that wrapped across printed lines.

    A bilingual filing sets the two languages side by side in the label column and lets the pair
    wrap together::

        Share of other comprehensive      應佔合營公司其他
        income of joint ventures          全面收益

    Reading that in printed order — which is what merging the two lines does — splices the
    languages into each other: "Share of other comprehensive 應佔合營公司其他 income of joint
    ventures 全面收益". The figures are right and the caption is complete, but neither language is
    a phrase any more, so an alias cannot match it and a model reading it has to reassemble two
    interleaved sentences before it can decide what the line is. Grouping the runs by script
    restores both: "Share of other comprehensive income of joint ventures" followed by
    "應佔合營公司其他全面收益".

    Applied only to a caption that genuinely spans more than one line, and only when the scripts
    actually alternate more than once. A single line reading "Goodwill (商譽) impairment" is in the
    order it was written, and reordering it would be the mistake this avoids.
    """
    if len(_label_lines(words)) < 2:
        return words
    runs: list[tuple[str | None, list[Word]]] = []
    for w in words:
        s = _script_of(w.text)
        if runs and (s is None or s == runs[-1][0]):
            runs[-1][1].append(w)
        else:
            runs.append((s, [w]))
    # A leading run of digits or punctuation belongs to whatever script follows it.
    if len(runs) > 1 and runs[0][0] is None:
        runs[1][1][:0] = runs[0][1]
        runs.pop(0)
    scripts = [s for s, _ in runs if s is not None]
    # Two runs is one language after the other — already contiguous, nothing to regroup.
    if len(set(scripts)) < 2 or len(runs) <= 2:
        return words
    order: list[str] = []
    for s in scripts:
        if s not in order:
            order.append(s)
    out: list[Word] = []
    for script in order:
        for s, ws in runs:
            if s == script:
                out.extend(ws)
    return out if len(out) == len(words) else words


def _join_words(words: list[Word]) -> str:
    """Words as a caption. No space is inserted between two Han tokens: Chinese is not written
    with spaces, and one inserted between "應佔合營公司其他" and "全面收益" stops the caption
    matching the alias an ontology actually lists."""
    parts: list[str] = []
    for w in words:
        if parts and _HAN.search(w.text) and _HAN.search(parts[-1][-1:]):
            parts[-1] = parts[-1] + w.text
        else:
            parts.append(w.text)
    return " ".join(parts).strip()


def _merge_wrapped_labels(rows: list[list[Word]], fmt=None,
                          steps: tuple[tuple[str, object], ...] = ()) -> list[list[Word]]:
    """Fold a label-only line into the following valued row when the two are clearly one
    wrapped label: tight vertical spacing *and* left-alignment inside the label column.

    Conservative on purpose — a wrong merge corrupts a label. A label-only line that reads
    like a section header, or that is loosely spaced / mis-aligned, is left untouched (the
    main loop then simply skips it, as before).
    """
    out: list[list[Word]] = []
    pending: list[Word] = []
    for idx, row in enumerate(rows):
        label_words, note_ref, value_words = _scan_row(row, fmt)
        if value_words:
            out.append(pending + row if pending else row)
            pending = []
            continue
        # Label-only (or note-only) line: candidate wrapped-label continuation.
        nxt = rows[idx + 1] if idx + 1 < len(rows) else None
        is_wrap = (
            nxt is not None
            and label_words
            and note_ref is None
            # An ALL-CAPS banner is not a continuation — unless grammar shows the caption
            # actually wraps into the next line (see `_is_wrapped_head`).
            and (not _looks_like_header(label_words, steps)
                 or _is_wrapped_head(label_words, _scan_row(nxt, fmt)[0]))
            and _scan_row(nxt, fmt)[2]                  # next row actually carries values
            and _wrap_adjacent(_row_box(row), _row_box(nxt), _scan_row(nxt, fmt)[0])
        )
        if is_wrap:
            pending = pending + row
        else:
            out.append(pending + row if pending else row)
            pending = []
    if pending:                                          # trailing label-only text, no value
        out.append(pending)
    return out


def _tight_below(cur: BBox, nxt: BBox) -> bool:
    """True when `nxt` is the next printed line of the same text block as `cur` — the vertical
    half of the wrap test, also used to walk a stacked column-header band line by line."""
    gap = nxt.y0 - cur.y1
    line_h = max(cur.y1 - cur.y0, 1e-4)
    return -0.5 * line_h <= gap <= 0.6 * line_h


def _wrap_adjacent(cur: BBox, nxt: BBox, nxt_label: list[Word]) -> bool:
    """True when `cur` sits directly above `nxt`'s label with paragraph-tight spacing."""
    if not _tight_below(cur, nxt):                       # tight spacing (same text block)
        return False
    label_x0 = min((w.bbox.x0 for w in nxt_label), default=nxt.x0)
    return abs(cur.x0 - label_x0) <= 0.06                # left-aligned in the label column


# ── The rulebook's scope_selection / normalisation blocks ────────────────────────────────────
#
# WHY reconstruction reads the rulebook at all. ``scope_selection`` is a statement about how a
# printed PAGE is read — which column is the Group's, which column is the current period, what
# scale the figures are in — and every one of those decisions is taken here, before mapping has
# an ontology in hand. Left to the engine's own regexes the declared block was decoration: a
# filing headed "Group | Company" (the HKEX house style) got NO basis bands at all, so every
# Company figure was filed as consolidated and quietly added to the Group's.
#
# The blocks are read from the rulebook shipped as the one in force, because ``stages.extract``
# runs before an ontology is attached to the run. A caller that does hold the run's pinned
# rulebook passes it instead (``build_line_items(scope=…, normalisation=…)``).
_RULEBOOK_IN_FORCE = (Path(__file__).resolve().parents[1] / "sample" / "templates"
                      / "hkfrs_hk_china_v2_ontology.json")


@lru_cache(maxsize=1)
def in_force_rules() -> tuple[ScopeSelection | None, Normalisation | None]:
    """``(scope_selection, normalisation)`` of the rulebook in force, or ``(None, None)``.

    Only those two blocks are validated, not the whole 173-concept rulebook: this is consulted
    for every page, and nothing else in the definition says anything about how a page is read.
    A block that will not validate governs nothing rather than stopping the extraction — the run
    still produces figures, and the log records which rules were applied.
    """
    try:
        raw = json.loads(_RULEBOOK_IN_FORCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    scope = norm = None
    if isinstance(raw.get("scope_selection"), dict):
        try:
            scope = ScopeSelection.model_validate(raw["scope_selection"])
        except Exception:                       # noqa: BLE001 — see the docstring
            scope = None
    if isinstance(raw.get("normalisation"), dict):
        try:
            norm = Normalisation.model_validate(raw["normalisation"])
        except Exception:                       # noqa: BLE001
            norm = None
    return scope, norm


# ── normalisation.pipeline ───────────────────────────────────────────────────────────────────
#
# The rulebook authors the text pipeline as an ORDERED list of steps in prose. Each declared step
# is matched to an implementation by the words it uses and they are applied in the order declared,
# so a step the rulebook adds, reorders or deletes changes what the engine does. That is the only
# way the list can be read as a specification: an unimplemented step is a policy a reviewer can
# look up and the engine ignores.
#
# The steps are used for COMPARISON only — never to rewrite ``source_label``, which has to stay
# exactly as printed for provenance.
_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")
# ``╱ ／ ⁄ → /``, ``（） → ()``, ``、 → ,`` and the fullwidth colon are named by the declared step;
# NFKC alone leaves ╱ and 、 untouched.
_WIDTH_MAP = {ord(c): "/" for c in "╱／⁄"} | {
    ord("（"): "(", ord("）"): ")", ord("、"): ",", ord("："): ":", ord("﹕"): ":",
    ord("；"): ";", ord("，"): ",", ord("　"): " ",
}
_SUPERSCRIPT = re.compile("[*\u2020\u2021#\u00b9\u00b2\u00b3\u2070-\u209f]+")
_NOTE_MARKER = re.compile(
    r"[(（]?\s*(?:notes?|附註|附注)\s*\.?\s*\d{1,3}[a-z]?(?:\s*\([a-z0-9]{1,3}\))?\s*[)）]?",
    re.IGNORECASE)
_TRAILING_PAREN_DIGITS = re.compile(r"\s*[(（]\s*\d{1,3}[a-z]?\s*[)）]\s*$")
_LEADING_NUMBERING = re.compile(
    r"^\s*(?:[(（]\s*(?:\d{1,3}|[a-z]|[ivx]{1,4}|[一二三四五六七八九十]{1,3})\s*[)）]"
    # The comma is in the delimiter set because the declared width step has already mapped 、 to
    # it by the time this runs — the rulebook lists the steps in that order.
    r"|(?:\d{1,3}|[一二三四五六七八九十]{1,3})\s*[.、,，·)]"
    r"|[-－–—•·‧])\s*")
_TRAILING_SUBCAPTION = re.compile(r"[\s:;\-－–—]+$")
_AUDIT_STATUS = re.compile(
    r"[(（]?\s*(?:un)?audited\s*[)）]?"
    r"|[(（]?\s*(?:未經審核|未经审核|經審核|经审核|未經審計|未经审计)\s*[)）]?", re.IGNORECASE)
# The literal examples a declared step names ('(a)', "RMB'000", '（未經審核）') are the step's own
# vocabulary; harvesting them means the rulebook, not this module, lists the tokens.
_QUOTED_EXAMPLE = re.compile(r"'([^']{1,24})'|\"([^\"]{1,24})\"|“([^”]{1,24})”")


def _quoted_examples(step: str) -> tuple[str, ...]:
    out: list[str] = []
    for m in _QUOTED_EXAMPLE.finditer(step):
        tok = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if tok:
            out.append(tok)
    return tuple(out)


def _fold_for_match(text: str) -> str:
    """Whitespace- and apostrophe-insensitive form, so "RMB '000" matches the declared "RMB'000"."""
    t = unicodedata.normalize("NFKC", text).translate(_WIDTH_MAP).lower()
    for q in "’‘`´":
        t = t.replace(q, "'")
    return re.sub(r"\s+", "", t)


def _strip_literals(text: str, literals: tuple[str, ...]) -> str:
    """Remove each declared literal, matched insensitively to spacing and apostrophe glyph."""
    for lit in literals:
        folded = _fold_for_match(lit)
        if not folded:
            continue
        # Rebuilt as a spacing-tolerant pattern rather than a plain replace: the printed caption
        # sets "RMB '000" and "人民幣 千元" with the space the alias does not carry.
        pat = r"\s*".join(re.escape(ch) for ch in folded)
        text = re.sub(pat, " ", text, flags=re.IGNORECASE)
    return text


_PIPELINE_IMPL: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nfkc", re.compile(r"\bnfkc\b", re.IGNORECASE)),
    ("t2s", re.compile(r"simplified", re.IGNORECASE)),
    ("case_fold", re.compile(r"case[\s-]?fold|lower\s?case", re.IGNORECASE)),
    ("width", re.compile(r"full-?width|half-?width", re.IGNORECASE)),
    ("footnote", re.compile(r"footnote", re.IGNORECASE)),
    ("numbering", re.compile(r"leading numbering|bullet", re.IGNORECASE)),
    ("trailing_colon", re.compile(r"trailing colon", re.IGNORECASE)),
    ("annotation", re.compile(r"unit and currency annotation", re.IGNORECASE)),
    ("whitespace", re.compile(r"whitespace|zero-width|soft hyphen", re.IGNORECASE)),
    # The wrapped-caption step is structural, not lexical: `_merge_wrapped_labels` reassembles the
    # caption from the printed lines before any of this runs, which is what the step asks for.
    ("wrapped_caption", re.compile(r"wrapped caption", re.IGNORECASE)),
)


def _pipeline_steps(norm: Normalisation | None,
                    scope: ScopeSelection | None = None) -> tuple[tuple[str, object], ...]:
    """The declared pipeline as (step id, callable) pairs, in the order the rulebook lists them.

    A declared step no implementation recognises is skipped rather than guessed at; an
    implementation whose step the rulebook drops stops running. Both directions matter — the
    rulebook is the specification, and this is the list of it that is actually in force.
    """
    if norm is None or not norm.pipeline:
        return ()
    unit_words = tuple(s for s in ((scope.units_and_currency.signals if scope else []) or [])
                       if s and s.strip())
    out: list[tuple[str, object]] = []
    for declared in norm.pipeline:
        for sid, pat in _PIPELINE_IMPL:
            if not pat.search(declared):
                continue
            examples = _quoted_examples(declared)
            if sid == "nfkc":
                out.append((sid, lambda t: unicodedata.normalize("NFKC", t)))
            elif sid == "t2s":
                out.append((sid, to_simplified))
            elif sid == "case_fold":
                out.append((sid, str.lower))
            elif sid == "width":
                out.append((sid, lambda t: t.translate(_WIDTH_MAP)))
            elif sid == "footnote":
                out.append((sid, lambda t, lits=examples: _TRAILING_PAREN_DIGITS.sub(
                    "", _SUPERSCRIPT.sub("", _NOTE_MARKER.sub(" ", _strip_literals(t, lits))))))
            elif sid == "numbering":
                out.append((sid, lambda t: _LEADING_NUMBERING.sub("", t)))
            elif sid == "trailing_colon":
                out.append((sid, lambda t: _TRAILING_SUBCAPTION.sub("", t)))
            elif sid == "annotation":
                # The declared units_and_currency signals are the same annotations printed inline
                # over a column, so one list serves both jobs.
                lits = examples + unit_words
                out.append((sid, lambda t, lits=lits: _AUDIT_STATUS.sub(
                    " ", _strip_literals(t, lits))))
            elif sid == "whitespace":
                out.append((sid, lambda t: re.sub(r"\s+", " ", _ZERO_WIDTH.sub("", t))))
            else:                                # wrapped_caption — see _PIPELINE_IMPL
                out.append((sid, lambda t: t))
            break
    return tuple(out)


def apply_pipeline(text: str, steps: tuple[tuple[str, object], ...] = (), *,
                   exclude: tuple[str, ...] = ()) -> str:
    """Run the declared pipeline over a caption, skipping the ``exclude``d step ids.

    ``exclude`` exists for the two places where a step would destroy the very property being
    tested: ``case_fold`` erases the ALL-CAPS shape ``_looks_like_header`` reads, and
    ``trailing_colon`` erases the colon that separates a sub-heading from a section banner.
    """
    for sid, fn in steps:
        if sid in exclude:
            continue
        text = fn(text)                          # type: ignore[operator]
    return text.strip()


def _ends_with_colon(text: str, steps: tuple[tuple[str, object], ...]) -> bool:
    """Whether a caption ends in a colon, fullwidth one included.

    A bilingual filing writes "其他全面收益：" with the FULLWIDTH colon, which a bare
    ``endswith(":")`` does not see — so the sub-heading was taken for a section banner and
    displaced the section for every row beneath it. The rulebook's fullwidth→halfwidth step is
    what makes it count.
    """
    return apply_pipeline(text, steps, exclude=("case_fold", "trailing_colon")).endswith(":")


# ── scope_selection.entity_scope ─────────────────────────────────────────────────────────────
#
# Which side of a two-basis column header a declared signal names. ``entity_scope.signals`` is one
# flat list ("Group", "Consolidated", 本集團, 綜合, "Company", 本公司), so the side has to be read
# off the wording — but the VOCABULARY is the rulebook's: a signal it does not declare is not
# detected, and one it adds is.
_GROUP_WORDS = re.compile(r"group|consolidat|集團|集团|綜合|综合|合併|合并", re.IGNORECASE)
_COMPANY_WORDS = re.compile(r"company|standalone|separate|公司|單獨|单独", re.IGNORECASE)
# Read with the v2 signal list alone, a statement headed "Consolidated | Standalone" would lose
# its Company side ("Standalone"/"Separate" are not declared) and the both-or-nothing rule would
# then refuse the whole header. These are the two words the engine read before any rulebook
# declared one, kept as a compatibility vocabulary — not as a widening of it.
_LEGACY_SIGNALS = ("Consolidated", "Standalone", "Separate")


def _norm_signal(text: str) -> str:
    """A header cell reduced to its bare word, for an ANCHORED comparison against a signal."""
    t = unicodedata.normalize("NFKC", text).translate(_WIDTH_MAP).strip()
    return t.strip("()[]{}:;,.'\"“”‘’*†‡#-–—_ ").lower()


def _entity_signals(scope: ScopeSelection | None) -> tuple[tuple[Basis, str], ...]:
    declared = list((scope.entity_scope.signals if scope else []) or [])
    out: list[tuple[Basis, str]] = []
    for sig in declared + [s for s in _LEGACY_SIGNALS if s not in declared]:
        word = _norm_signal(sig)
        if not word:
            continue
        if _GROUP_WORDS.search(word):
            out.append((Basis.CONSOLIDATED, word))
        elif _COMPANY_WORDS.search(word):
            out.append((Basis.STANDALONE, word))
    return tuple(dict.fromkeys(out))


def _signal_side(token: str, signals: tuple[tuple[Basis, str], ...]) -> Basis | None:
    """The basis a header CELL names, or None.

    Anchored on the whole cell, and deliberately not sharing ``_CONSOL``/``_STANDALONE`` with
    ``_matrix_basis``: that one scans whole-page text, where "the Company" and "… Company
    Limited" appear constantly. Here the cell must BE the signal, so a running header and a note
    sentence about the Company cannot define a band.
    """
    word = _norm_signal(token)
    if not word:
        return None
    return next((b for b, s in signals if s == word), None)


def _company_only_stems(scope: ScopeSelection | None) -> tuple[tuple[str, ...], ...]:
    """Caption stems for each declared ``company_only_markers`` entry.

    The marker is declared as a canonical_key inside a sentence ("Presence of
    bs_non_current_assets__investments_in_subsidiaries on the face is strong evidence the column
    is company-only, since consolidation eliminates it"), so the stems come from the key's own
    tail: ``investments_in_subsidiaries`` → "investment" + "subsidiar".
    """
    stop = {"in", "of", "and", "to", "the", "for", "on", "at", "a"}
    out: list[tuple[str, ...]] = []
    for marker in ((scope.entity_scope.company_only_markers if scope else []) or []):
        for tail in re.findall(r"[a-z][a-z0-9_]*__([a-z0-9_]+)", marker):
            stems = []
            for tok in tail.split("_"):
                if tok in stop or len(tok) < 3:
                    continue
                stems.append(tok[:-3] if tok.endswith("ies") else tok.rstrip("s"))
            if stems:
                out.append(tuple(stems))
    return tuple(out)


def _names_company_only(label: str, stems: tuple[tuple[str, ...], ...]) -> bool:
    low = label.lower()
    return any(all(s in low for s in group) for group in stems)


_CONSOL = re.compile(r"consolidat", re.IGNORECASE)
_STANDALONE = re.compile(r"standalone|separate", re.IGNORECASE)
# The header area. A basis caption belongs to the column header, exactly as a period caption does
# (`_period_bands` has always been bounded this way).
_HDR_ROWS = 8
# Clear air between two column captions. Word spacing inside one phrase is an order of magnitude
# tighter, which is what separates a two-caption band row from a sentence naming both entities.
_CAPTION_GAP = 0.03


def _carries_amounts(row: list[Word], fmt=None) -> bool:
    """Whether a row reports a real figure (a year or a day-of-month is not one)."""
    for w in row:
        tok = w.text.strip()
        d = _num(tok, fmt)
        if d is not None and _is_money_like(tok, fmt) and not _is_date_ish(d):
            return True
    return False


def _value_area(value_bands: list[float],
                col_xs: list[list[tuple[float, str]]]) -> tuple[float, float] | None:
    """The horizontal extent of the page's figures, from the detected columns when there are any
    and from the figures themselves when the page is too sparse to have columns."""
    xs = list(value_bands) or sorted(x for row in col_xs for x, _ in row)
    return (xs[0], xs[-1]) if len(xs) >= 2 else None


def _over_value_columns(xc: float, area: tuple[float, float] | None) -> bool:
    """Whether a caption stands OVER the figures it would band.

    Prose mentioning the Group and the Company sits in the label column; a column caption sits
    above the numbers. Without this test one sentence on a notes page defines the page's bands.
    """
    if area is None:
        return False
    lo, hi = area
    pad = max(0.05, (hi - lo) * 0.25)
    return lo - pad <= xc <= hi + pad


def _nearest_col(x: float, value_bands: list[float]) -> int | None:
    if not value_bands:
        return None
    return min(range(len(value_bands)), key=lambda i: abs(value_bands[i] - x))


def _basis_bands(rows: list[list[Word]], value_bands: list[float] | None = None,
                 area: tuple[float, float] | None = None, *,
                 signals: tuple[tuple[Basis, str], ...] = (), fmt=None,
                 log=None, page_index: int | None = None) -> list[tuple[Basis, float]]:
    """Detect a two-basis column header (Group | Company, Consolidated | Standalone) and return
    each basis caption's horizontal centre, so value columns can be attributed to a basis.

    Every guard here answers a way the previous version got it wrong, and each of them is why the
    result is empty (single-basis, everything consolidated) rather than approximate:

    * It scanned EVERY row, so any prose row mentioning one of the words could define the bands —
      on a notes page "The Group and the Company had no material contingent liabilities" is such
      a row. Bounded now to the header area, which narrows the existing Consolidated/Standalone
      detection too: that is the intent, a basis caption is part of the column header.
    * It ran on the MERGED rows, where a wrapped basis caption has been glued onto the period
      line — the geometry the tests below rely on then describes the merged block, not the print.
      The caller passes the unmerged rows.
    * ``_basis_for`` returns the NEAREST band, so ONE stray caption relabels a whole page. Both
      sides must be present (both-or-nothing) and each must sit over the value columns.
    * A false positive does not merely mislabel: it SPLITS a two-column comparative, so last
      year's figures are read as this year's for another entity. Corrupting the periods is worse
      than leaving the Group/Company gap open, so every test is a veto.
    """
    signals = signals or _entity_signals(None)
    for row in rows[:_HDR_ROWS]:
        # A band row captions columns; a row that also reports an amount is a statement line, or
        # prose citing one.
        if _carries_amounts(row, fmt):
            continue
        hits: list[tuple[Basis, float, int]] = []
        for ri, run in enumerate(_x_runs(row, _CAPTION_GAP)):
            for w in run:
                side = _signal_side(w.text, signals)
                if side is not None and _over_value_columns(_xc(w), area):
                    hits.append((side, _xc(w), ri))
        if len({b for b, _, _ in hits}) < 2:
            continue                              # both-or-nothing
        group = [(x, ri) for b, x, ri in hits if b is Basis.CONSOLIDATED]
        company = [(x, ri) for b, x, ri in hits if b is Basis.STANDALONE]
        if {ri for _, ri in group} & {ri for _, ri in company}:
            # One contiguous phrase naming both ("The Group and the Company had no…") is a
            # sentence. Two captions stand apart, each over its own columns.
            continue
        cols_g = {_nearest_col(x, value_bands or []) for x, _ in group}
        cols_c = {_nearest_col(x, value_bands or []) for x, _ in company}
        if value_bands and cols_g & cols_c:
            continue                              # both captions over one column: nothing to split
        if not value_bands and min(abs(gx - cx) for gx, _ in group for cx, _ in company) < 0.08:
            continue                              # too close together to be separate columns
        bands = [(b, x) for b, x, _ in hits]
        if log:
            named = ",".join(f"{b.value}@{x:.2f}" for b, x in bands)
            log(f"extract:page={page_index}:entity_scope=two_basis_header({named})")
        return bands
    return []


def _basis_for(x: float, bands: list[tuple[Basis, float]]) -> Basis:
    if not bands:
        return Basis.CONSOLIDATED
    return min(bands, key=lambda b: abs(b[1] - x))[0]


# Value columns are printed on a tight vertical alignment — every figure in the current-period
# column shares an x-centre to within a fraction of the column gap. This is the width within
# which two figures are taken to be in the same column.
_COL_TOL = 0.035
# A column has to be used by several rows to be a column at all, so a stray figure in a footnote
# or a page number never becomes one.
_COL_MIN_ROWS = 3


def _value_column_bands(value_xs: list[list[tuple[float, str]]]) -> list[float]:
    """The x-centres of the statement's value columns, from the figures on the page.

    A row's period CANNOT be taken from the order of its own values. When a filing reports a line
    in one period only — "Pledged deposits" with a prior-year figure and no current one — the
    single figure sits under the PRIOR column, and reading it as "the first value, therefore
    current" files real money against the wrong year. It is silent: the row looks fine, and only
    the section subtotal reveals it, over-stating one period and under-stating the other by the
    same amount.

    A note-reference column is excluded, because it is not a period. Statements print note refs
    in their own narrow column, and where enough rows carry one it aligns as tightly as any money
    column — so taken as column 0 it makes every real figure on the page one period too late, and
    a whole page of current-year figures is filed against the prior year. What distinguishes it is
    its contents: bare 1–2 digit integers, never formatted amounts.

    Returns [] when the page has no columnar structure to speak of, and the caller falls back to
    positional order.
    """
    flat = sorted((x, t) for xs in value_xs for x, t in xs)
    if not flat:
        return []
    clusters: list[list[tuple[float, str]]] = [[flat[0]]]
    for item in flat[1:]:
        if item[0] - clusters[-1][-1][0] <= _COL_TOL:
            clusters[-1].append(item)
        else:
            clusters.append([item])

    def is_note_column(cluster: list[tuple[float, str]]) -> bool:
        notes = sum(1 for _, t in cluster if _is_note_number(t))
        return notes >= max(2, int(0.8 * len(cluster)))

    kept = [c for c in clusters if len(c) >= _COL_MIN_ROWS and not is_note_column(c)]
    if len(kept) < 2:
        return []                       # nothing to disambiguate; order is as good as position
    return [sorted(x for x, _ in c)[len(c) // 2] for c in kept]   # median resists one outlier


def _column_index(x: float, bands: list[float]) -> int | None:
    """Which value column a figure sits in, or None when it is nowhere near one."""
    if not bands:
        return None
    idx = min(range(len(bands)), key=lambda i: abs(bands[i] - x))
    return idx if abs(bands[idx] - x) <= _COL_TOL * 2 else None


def _detect_note_column(rows: list[list[Word]]) -> float | None:
    """The x-centre of the note-reference column, if the statement has one. Found from a
    'Notes'/'附註' column header that is BACKED by a vertical run of bare note numbers beneath
    it (≥2), so an inline 'Note 14' mention in prose isn't mistaken for a column. Returns None
    when there's no such column (then a per-row heuristic handles a leading note number)."""
    header_xs: list[float] = []
    for row in rows:
        for w in row:
            if _NOTE_HDR.match(w.text.strip()):
                header_xs.append((w.bbox.x0 + w.bbox.x1) / 2)
    best, best_n = None, 0
    for cx in header_xs:
        n = 0
        for row in rows:
            if any(abs((w.bbox.x0 + w.bbox.x1) / 2 - cx) <= 0.03 and _is_note_number(w.text)
                   for w in row):
                n += 1
        if n > best_n:
            best, best_n = cx, n
    return best if best_n >= 2 else None


def _resolve_note_column(note_ref: str | None, value_words: list[Word],
                         note_x: float | None, fmt=None) -> tuple[str | None, list[Word]]:
    """Separate the note-reference cell from the monetary values. When a note column was detected,
    a value token sitting in it (and shaped like a note number) is the reference. Otherwise, a
    leading bare 1–2 digit integer followed by a real amount is treated as the note ref — the
    common ``Revenue  6  45,230  40,110`` layout, where '6' is Note 6, not the current-year value."""
    if note_ref is not None or not value_words:
        return note_ref, value_words
    if note_x is not None:
        kept: list[Word] = []
        for vw in value_words:
            xc = (vw.bbox.x0 + vw.bbox.x1) / 2
            if note_ref is None and abs(xc - note_x) <= 0.03 and _is_note_number(vw.text):
                note_ref = vw.text.strip().strip(".")
            else:
                kept.append(vw)
        return note_ref, kept
    if (len(value_words) >= 2 and _is_note_number(value_words[0].text)
            and any(_is_money_like(w.text, fmt) for w in value_words[1:])):
        return value_words[0].text.strip().strip("."), value_words[1:]
    return note_ref, value_words


_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
           r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
# A single word that can belong to a date-column header phrase.
_DATEISH_WORD = re.compile(
    rf"^(?:{_MONTHS}|\d{{1,4}}(?:st|nd|rd|th)?|\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|"
    r"as|at|year|years?|period|ended|ending|for|the|fy|q[1-4]|h[12]|,)$", re.IGNORECASE)
# A phrase only counts as a period header if it actually carries a year or month name.
_DATE_PHRASE = re.compile(rf"(?:19|20)\d{{2}}|{_MONTHS}", re.IGNORECASE)


def _period_bands(rows: list[list[Word]]) -> list[tuple[str, float]]:
    """Detect date-like column headers (e.g. '31 March 2025' / '2024' / 'FY2025') near the top
    of a statement block and return each period phrase's (label, x-centre). Used to give value
    columns a real period-end DATE for display; empty when no dated header is found (native
    PDFs without a parsable header fall back to positional Current/Prior)."""
    best: list[tuple[str, float]] = []
    for row in rows[:8]:                          # period headers sit at the top of the block
        phrases: list[list[Word]] = []
        run: list[Word] = []
        for w in row:
            dateish = bool(_DATEISH_WORD.match(w.text.strip(" .")))
            # A wide horizontal gap means a new column — flush the current phrase even between
            # two date-ish words (e.g. "…2025    31 March 2024" are two separate headers).
            gap = run and (w.bbox.x0 - run[-1].bbox.x1) > 0.05
            if dateish and not gap:
                run.append(w)
            else:
                if run:
                    phrases.append(run); run = []
                if dateish:
                    run.append(w)
        if run:
            phrases.append(run)
        bands: list[tuple[str, float]] = []
        for ph in phrases:
            text = " ".join(w.text for w in ph).strip(" ,.")
            if _DATE_PHRASE.search(text):         # keep only phrases with a real year/month
                xc = sum((w.bbox.x0 + w.bbox.x1) / 2 for w in ph) / len(ph)
                bands.append((text, xc))
        if len(bands) > len(best):
            best = bands
        if len(bands) >= 2:                        # a two-column header is a confident match
            break
    return best


def _period_for(x: float, bands: list[tuple[str, float]]) -> str | None:
    """The detected period label whose column is nearest this value's x-centre, or None."""
    if not bands:
        return None
    return min(bands, key=lambda b: abs(b[1] - x))[0]


# ── scope_selection.period_selection ─────────────────────────────────────────────────────────
#
# "Identify the current period from the column heading date, not from column position; HKEX
# filings are not consistently current-first." Reading position instead files every figure a year
# out on any filing that prints the comparative on the left — and nothing downstream can see it,
# because each column is internally consistent.
_CJK_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CJK_NUM = re.compile(r"^[〇零一二三四五六七八九十]{1,4}$")
_MONTH_NAMES = ("jan", "feb", "mar", "apr", "may", "jun",
                "jul", "aug", "sep", "oct", "nov", "dec")


def _cjk_number(text: str) -> int | None:
    """A CJK numeral as an integer: 二零二三 → 2023, 十二 → 12, 三十一 → 31."""
    if not _CJK_NUM.match(text):
        return None
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CJK_DIGIT.get(left, 1) if left else 1
        ones = _CJK_DIGIT.get(right, 0) if right else 0
        return tens * 10 + ones
    out = 0
    for ch in text:
        out = out * 10 + _CJK_DIGIT[ch]
    return out


def _period_date(text: str) -> tuple[int, int, int] | None:
    """``(year, month, day)`` read from a column heading, or None when it names no year.

    Month and day default to 0 so "2024" ranks below "31 December 2024" only when the two are
    genuinely different periods; what matters is that the ORDER is the printed dates' order.
    """
    if not text:
        return None
    t = unicodedata.normalize("NFKC", text)
    year = month = day = 0
    m = re.search(r"(?:19|20)\d{2}", t)
    if m:
        year = int(m.group(0))
    else:
        m = re.search(r"([〇零一二三四五六七八九十]{2,4})年", t)
        if m:
            year = _cjk_number(m.group(1)) or 0
    if not year:
        return None
    mn = re.search(r"([〇零一二三四五六七八九十]{1,3})月", t)
    if mn:
        month = _cjk_number(mn.group(1)) or 0
    else:
        low = t.lower()
        for i, name in enumerate(_MONTH_NAMES, start=1):
            if name in low:
                month = i
                break
    dn = re.search(r"([〇零一二三四五六七八九十]{1,3})日", t)
    if dn:
        day = _cjk_number(dn.group(1)) or 0
    else:
        dm = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?=[a-z])", t, re.IGNORECASE)
        if dm:
            day = int(dm.group(1))
    # A numeric date ("31/12/2024", "2024-12-31") carries month and day in its own separators.
    nd = re.search(r"\b(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})\b", t)
    if nd and not month:
        a, b, c = (int(g) for g in nd.groups())
        if a > 31:                     # y-m-d
            month, day = b, c
        else:                          # d-m-y
            month, day = b, a
    return year, month, day


def _restated_markers(scope: ScopeSelection | None) -> tuple[str, ...]:
    """The captions ``restatement_rule`` says mark a restated comparative.

    Harvested from the declared sentence ("Where a comparative column is labelled restated / 重列
    / 經重列, load it as the comparative and set restated: true") rather than listed here, so a
    filing spelling it a fourth way is closed by editing the rulebook. Nothing is assumed when the
    sentence names nothing: restatement handling then simply does not apply.
    """
    rule = (scope.period_selection.restatement_rule if scope else "") or ""
    m = re.search(r"labelled\s+([^,.;]+)", rule, re.IGNORECASE)
    if not m:
        return ()
    return tuple(t for t in (p.strip().lower() for p in m.group(1).split("/")) if t)


def _is_restated(head: str, markers: tuple[str, ...]) -> bool:
    low = to_simplified(unicodedata.normalize("NFKC", head or "")).lower()
    return any(to_simplified(mk) in low for mk in markers)


def _restated_columns(rows: list[list[Word]], value_bands: list[float],
                      markers: tuple[str, ...]) -> set[int]:
    """Value columns whose header carries a restatement marker.

    Read from the header area directly rather than from ``_period_bands``, because the marker is
    not a date: "(restated)" / "經重列" is printed on its own line under the year, so the period
    phrase never contains it and the column looked like an ordinary comparative.
    """
    out: set[int] = set()
    if not markers or not value_bands:
        return out
    for row in rows[:_HDR_ROWS]:
        for w in row:
            if not _is_restated(_norm_signal(w.text), markers):
                continue
            col = _nearest_col(_xc(w), value_bands)
            if col is not None and abs(value_bands[col] - _xc(w)) <= 0.06:
                out.add(col)
    return out


def _column_periods(basis_cols: dict[Basis, list[int]], value_bands: list[float],
                    period_bands: list[tuple[str, float]], *,
                    restated: tuple[str, ...] = (), restated_cols: set[int] | None = None,
                    log=None, page_index: int | None = None) -> dict[tuple[Basis, int], str]:
    """The period label for every (basis, value column).

    Ordering is by the column HEADING DATE when every column of a basis carries one, and by
    printed position otherwise — a page whose header cannot be read offers nothing better, and
    guessing would be the mistake this exists to prevent.

    ``restatement_rule``: a comparative headed "(restated)" loads as the comparative. When the
    original is printed BESIDE it the two share a slot, and the restated column takes a
    distinguished label instead of overwriting the original — the rulebook's "keep both with a
    restatement flag", within a ``ValueKey`` that has nowhere to put the flag itself.
    """
    out: dict[tuple[Basis, int], str] = {}
    for basis, cols in basis_cols.items():
        heads = {c: (_period_for(value_bands[c], period_bands) or "") for c in cols}
        dates = {c: _period_date(heads[c]) for c in cols}
        flags = {c: _is_restated(heads[c], restated) or c in (restated_cols or set())
                 for c in cols}
        groups = sorted({d for d in dates.values() if d}, reverse=True)
        by_date = len(groups) > 1 and all(dates[c] for c in cols)
        if by_date:
            slot_of = {c: groups.index(dates[c]) for c in cols}
            order = sorted(cols, key=lambda c: (slot_of[c], flags[c]))
            if order != sorted(cols) and log:
                log(f"extract:page={page_index}:period_selection=by_heading_date"
                    f"({'|'.join(heads[c] for c in order)})")
        else:
            slot_of = {c: i for i, c in enumerate(sorted(cols))}
            order = sorted(cols, key=lambda c: (slot_of[c], flags[c]))
        used: set[str] = set()
        for c in order:
            i = slot_of[c]
            base = "current" if i == 0 else "prior" if i == 1 else f"col{i}"
            label = base
            if base in used:
                label = f"{base}_restated" if flags[c] else f"{base}_col{c}"
                if log:
                    log(f"extract:page={page_index}:period_selection=kept_both"
                        f"({basis.value}/{label})")
            elif flags[c] and log:
                log(f"extract:page={page_index}:period_selection=restated({basis.value}/{base})")
            used.add(label)
            out[(basis, c)] = label
    return out


# ── scope_selection.units_and_currency ───────────────────────────────────────────────────────
#
# "Resolve currency and scale from the statement header, not the cover page, and re-resolve per
# statement. Persist unit on every fact; never normalise scale silently." Reconstruction runs per
# PAGE, so the header it reads is the statement's own — a cover-page banner cannot reach it — and
# the resolved unit is written onto every fact rather than onto the document.
_SCALE_WORDS: tuple[tuple[re.Pattern[str], Decimal, str], ...] = (
    (re.compile(r"'0{3}|thousand", re.IGNORECASE), Decimal(1_000), "thousand"),
    (re.compile(r"千元|千"), Decimal(1_000), "thousand"),
    (re.compile(r"million", re.IGNORECASE), Decimal(1_000_000), "million"),
    (re.compile(r"百萬元|百万元|百萬|百万"), Decimal(1_000_000), "million"),
    (re.compile(r"billion", re.IGNORECASE), Decimal(1_000_000_000), "billion"),
    (re.compile(r"億元|亿元|億|亿"), Decimal(100_000_000), "hundred million"),
)
_CURRENCY_WORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"rmb|cny|人民幣|人民币|元人民幣", re.IGNORECASE), "CNY"),
    (re.compile(r"hk\$|hkd|港幣|港币|港元", re.IGNORECASE), "HKD"),
    (re.compile(r"us\$|usd|美元", re.IGNORECASE), "USD"),
    (re.compile(r"eur|€", re.IGNORECASE), "EUR"),
    (re.compile(r"gbp|£", re.IGNORECASE), "GBP"),
    (re.compile(r"₹|inr|rs\.?", re.IGNORECASE), "INR"),
)


def _unit_signals(scope: ScopeSelection | None) -> tuple[tuple[str, str, Decimal, str], ...]:
    """``(folded signal, currency, scale, scale word)`` for every declared units signal.

    Longest first, so "RMB million" is tested before a signal that is a prefix of it. A currency
    or scale the rulebook does not declare is not read off the page: the signal list is the
    vocabulary, and adding to it is how a filing in a new currency is supported.
    """
    out: list[tuple[str, str, Decimal, str]] = []
    for sig in ((scope.units_and_currency.signals if scope else []) or []):
        folded = _fold_for_match(sig)
        if not folded:
            continue
        ccy = next((c for rx, c in _CURRENCY_WORDS if rx.search(sig)), "")
        scale = next(((s, w) for rx, s, w in _SCALE_WORDS if rx.search(sig)), None)
        if not ccy and scale is None:
            continue
        out.append((folded, ccy, scale[0] if scale else Decimal(1), scale[1] if scale else ""))
    return tuple(sorted(out, key=lambda t: -len(t[0])))


def _header_rows(rows: list[list[Word]], fmt=None) -> list[list[Word]]:
    """The statement header: the rows above the first one that reports a figure, bounded.

    This is what "from the statement header, not the cover page" means for a page: the units
    caption is printed with the column heads, never among the figures.
    """
    out: list[list[Word]] = []
    for row in rows[:_HDR_ROWS]:
        out.append(row)
        if _carries_amounts(row, fmt):
            break
    return out


def _unit_context(unit: tuple[str, Decimal, str] | None, page_index: int) -> UnitContext:
    """The resolved unit as it is persisted on a fact. An unresolved unit stays EMPTY — the scale
    is never guessed, because "never normalise scale silently" cuts both ways."""
    if unit is None:
        return UnitContext()
    return UnitContext(currency=unit[0], scale_factor=unit[1], units_label=unit[2],
                       source_bbox_page=page_index)


def _statement_unit(rows: list[list[Word]], signals: tuple[tuple[str, str, Decimal, str], ...],
                    fmt=None) -> tuple[str, Decimal, str] | None:
    """``(currency, scale, printed label)`` declared in this statement's header, or None."""
    for row in _header_rows(rows, fmt):
        blob = _fold_for_match(" ".join(w.text for w in row))
        for folded, ccy, scale, word in signals:
            if folded in blob:
                return ccy, scale, word or folded
    return None


_TOTAL_LABEL = re.compile(r"^\s*(?:total|sub-?total)\b|總額|总额|合計|合计|總計|总计|小計|小计",
                          re.IGNORECASE)


def _conflict_factor(scope: ScopeSelection | None) -> Decimal | None:
    """The factor ``units_and_currency.conflict`` calls inconsistent, from the declared sentence
    ("inconsistent by a factor of 1,000"). No factor declared, no check."""
    text = (scope.units_and_currency.conflict if scope else "") or ""
    m = re.search(r"factor of\s+([\d,]+)", text, re.IGNORECASE)
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _scale_conflict(rows: list[list[Word]], factor: Decimal, fmt=None,
                    steps: tuple[tuple[str, object], ...] = ()) -> str | None:
    """A printed subtotal inconsistent with the lines it totals by exactly ``factor``.

    That is the shape of the conflict the rulebook describes: the header declares one scale and a
    figure on the page is printed in another. Trusting either half silently mis-states the
    statement by three orders of magnitude, so the caller drops the unit and routes the statement
    to review — the one case where reporting nothing is the correct answer.
    """
    run: list[Decimal] = []
    for row in rows:
        label_words, _, value_words = _scan_row(row, fmt)
        label = apply_pipeline(_join_words(label_words), steps)
        vals = [d for d in (_num(w.text, fmt) for w in
                            sorted(value_words, key=lambda w: w.bbox.x0)) if d is not None]
        # A header or running-header row that leaked in would corrupt the sum, and a year is
        # indistinguishable from an amount once it is in it — so the same noise test the main loop
        # applies decides what counts as a line here.
        if not label or not vals or _is_noise_row(label, vals, steps):
            continue
        first = vals[0]
        if _TOTAL_LABEL.search(label):
            total = sum(run)
            if len(run) >= 2 and total and first:
                ratio = abs(first / total)
                for probe in (factor, Decimal(1) / factor):
                    if probe and abs(ratio - probe) <= probe / 100:
                        return f"subtotal({first})/sum({total})~{probe}"
            run = []
            continue
        run.append(first)
    return None


# ── scope_selection.column_guard ─────────────────────────────────────────────────────────────


_GUARD_DIMS = ("entity_scope", "period", "currency", "unit")


def guard_dimensions(scope: ScopeSelection | None) -> tuple[str, ...]:
    """The dimensions the rulebook says identify a fact, read off ``column_guard`` itself:
    "Every fact carries the resolved (entity_scope, period, currency, unit). Two facts for the
    same canonical_key that differ on any of these are distinct facts, not duplicates."
    """
    text = (scope.column_guard if scope else "") or ""
    m = re.search(r"\(([^)]*)\)", text)
    if not m:
        return ()
    named = [d.strip().lower().replace(" ", "_") for d in m.group(1).split(",")]
    return tuple(d for d in named if d in _GUARD_DIMS)


def _fact_identity(ev: ExtractedValue, dims: tuple[str, ...]) -> tuple:
    parts: list[object] = []
    for d in dims:
        if d == "entity_scope":
            parts.append(ev.basis.value)
        elif d == "period":
            parts.append((ev.period_end, ev.period_label, ev.period_display))
        elif d == "currency":
            parts.append(ev.unit_ctx.currency)
        elif d == "unit":
            parts.append(str(ev.unit_ctx.scale_factor))
    return tuple(parts)


def store_fact(li: LineItem, ev: ExtractedValue, dims: tuple[str, ...] = (), *,
               log=None, where: str = "") -> None:
    """Store a fact on a row, keeping two facts apart when the rulebook says they are distinct.

    ``LineItem.values`` is keyed by (basis, period_end, period_label), which cannot express a
    difference in currency or scale — so a second fact differing only there used to REPLACE the
    first in silence, which is the duplicate-collapse ``column_guard`` forbids. It is kept under a
    distinguished period_label instead.

    And when two facts agree on every declared dimension they really are one fact read twice, so
    the FIRST is kept: a printed figure is not improved by a second reading of the same column,
    and overwriting it means the row silently reports whichever cell the geometry happened to
    visit last. Either way the collision is logged rather than hidden.
    """
    key = ev.key.model_dump_json()
    existing = li.values.get(key)
    if existing is None:
        li.set_value(ev)
        return
    if not dims or _fact_identity(existing, dims) == _fact_identity(ev, dims):
        if log:
            log(f"extract:{where}duplicate_fact_dropped({ev.basis.value}/{ev.period_label})")
        return
    base = ev.period_label or "col"
    label, n = f"{base}#2", 2
    while li.get_value(ev.basis, ev.period_end, label) is not None:
        n += 1
        label = f"{base}#{n}"
    li.set_value(ev.model_copy(update={"period_label": label}))
    if log:
        log(f"extract:{where}distinct_fact({ev.basis.value}/{label})")


# ── Matrix statements (consolidated statement of changes in equity) ──────────────────────
#
# A matrix face has one value column per equity COMPONENT, captioned by a bilingual header band
# ("Share" / "premium" / "account" / "股份" / "溢價賬" stacked over the column). Detection is
# geometric so a mis-classified page still parses: ≥5 value columns on ≥3 rows is a layout no
# two-column comparative produces (four columns is the maximum there — 2 bases × 2 periods).
_MATRIX_MIN_COLS = 5
_MATRIX_MIN_ROWS = 3
# Value cells are RIGHT-aligned in a printed statement, so a column's right edge is its stable
# anchor (a cell's centre drifts with the width of the number in it).
_COL_TOL = 0.012
# Footnote markers hang off reserve columns ("(3,596,236)*", "–*"). Left in place the token
# simply fails to parse and the column silently loses its value.
_FOOTMARK = re.compile(r"[*†#‡]+$")
_NIL_CELL = re.compile(r"^[-–—−]$")
# Header tokens that caption the units or the note reference for a column, not the component.
_UNITS_TOKEN = re.compile(r"[’'`]0{3}|千元|百萬元|億元|亿元|thousands?|millions?|billions?|"
                          r"lakhs?|crores?", re.IGNORECASE)
_NOTE_TOKEN = re.compile(r"note|附註|附注", re.IGNORECASE)


def _xc(w: Word) -> float:
    return (w.bbox.x0 + w.bbox.x1) / 2


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def _line_tol(words: list[Word]) -> float:
    """Row-clustering tolerance for a matrix, derived from the page's own line height.

    The default tolerance is deliberately generous so a slightly skewed scan still groups; in a
    matrix that generosity merges *adjacent* movement lines, which interleaves two captions and
    shifts every figure onto the wrong row. Half a line height keeps the lines apart.
    """
    hs = [w.bbox.y1 - w.bbox.y0 for w in words]
    return max(0.45 * _median(hs), 0.001)


def _cell_text(t: str) -> str:
    return _FOOTMARK.sub("", t.strip())


def _matrix_cells(row: list[Word], fmt=None) -> list[Word]:
    """The value-shaped tokens of a row. A nil dash counts: it carries no amount but it does
    mark a column position, which is what the column geometry is derived from."""
    out: list[Word] = []
    for w in row:
        t = _cell_text(w.text)
        if _NIL_CELL.match(t) or _num(t, fmt) is not None:
            out.append(w)
    return out


def _strong_cells(cells: list[Word], fmt=None) -> int:
    """How many cells are a real amount or a nil dash — i.e. not a bare 1–2 digit integer.
    A footnote line that prints a figure one digit per glyph ("9 , 3 5 8 , 6 1 1 , 0 0 0",
    as bilingual filings do) lands digits in the value columns; requiring a majority of real
    amounts keeps that line out of the matrix."""
    return sum(1 for w in cells
               if _NIL_CELL.match(_cell_text(w.text))
               or _is_money_like(_cell_text(w.text), fmt))


@dataclass
class _Matrix:
    rows: list[list[Word]]
    bands: list[tuple[float, float]]     # (left, right) x-extent of each component column
    first_data: int                      # row index of the first movement row
    pitch: float                         # median column pitch, the scale for header heuristics


def _pitch(edges: list[float]) -> float:
    return _median([edges[i + 1] - edges[i] for i in range(len(edges) - 1)]) or 1.0


def _detect_matrix(rows: list[list[Word]], fmt=None) -> _Matrix | None:
    """Geometry of a matrix face, or None when the page is not one.

    Columns come from the value rows themselves (clustered right edges) rather than from the
    header, because the header is what we then have to *attribute* to them — deriving both from
    the header would let a missing caption invent a column.
    """
    data_idx: list[int] = []
    cells_by_row: dict[int, list[Word]] = {}
    for i, row in enumerate(rows):
        cells = _matrix_cells(row, fmt)
        if len(cells) >= _MATRIX_MIN_COLS and _strong_cells(cells, fmt) * 2 >= len(cells):
            data_idx.append(i)
            cells_by_row[i] = cells
    if len(data_idx) < _MATRIX_MIN_ROWS:
        return None

    groups: list[list[float]] = []
    for e in sorted(w.bbox.x1 for i in data_idx for w in cells_by_row[i]):
        if groups and e - groups[-1][-1] <= _COL_TOL:
            groups[-1].append(e)
        else:
            groups.append([e])
    # A column of the matrix appears on most rows. A one-off cluster is a date fragment in a
    # label ("At 1 January 2022") or an inline note reference, not a column.
    min_support = max(2, (len(data_idx) + 2) // 3)
    edges = [_median(g) for g in groups if len(g) >= min_support]
    if len(edges) < _MATRIX_MIN_COLS:
        return None
    # Trim clusters standing off on their own — a note column, or label digits that happened to
    # line up — so the value area is the evenly pitched run of component columns.
    while len(edges) > _MATRIX_MIN_COLS and edges[1] - edges[0] > 2.5 * _pitch(edges):
        edges.pop(0)
    while len(edges) > _MATRIX_MIN_COLS and edges[-1] - edges[-2] > 2.5 * _pitch(edges):
        edges.pop()
    pitch = _pitch(edges)
    bands = [(edges[0] - pitch if k == 0 else edges[k - 1], edges[k])
             for k in range(len(edges))]
    return _Matrix(rows=rows, bands=bands, first_data=data_idx[0], pitch=pitch)


def _band_of(w: Word, bands: list[tuple[float, float]]) -> int | None:
    """The component column this word sits in, by x-centre — the same banding idea
    ``_period_bands``/``_basis_bands`` use for periods and bases."""
    xc = _xc(w)
    for k, (left, right) in enumerate(bands):
        if left < xc <= right:
            return k
    return None


def _x_runs(row: list[Word], gap: float) -> list[list[Word]]:
    """Split a header row into horizontally contiguous phrases. A caption sits inside one
    column with clear air on both sides; a *spanner* ("Attributable to owners of the parent")
    is one tight phrase laid across several columns and must not be read as any of their names.
    """
    runs: list[list[Word]] = []
    for w in row:
        if runs and w.bbox.x0 - runs[-1][-1].bbox.x1 <= gap:
            runs[-1].append(w)
        else:
            runs.append([w])
    return runs


def _caption_words(row: list[Word], m: _Matrix) -> dict[int, list[Word]]:
    """The words of one header row that genuinely caption a single column, keyed by column."""
    out: dict[int, list[Word]] = {}
    # Word spacing scales with the column width, so the "clear air" that separates two captions
    # is measured against the pitch rather than a fixed fraction of the page.
    for run in _x_runs(row, max(0.004, 0.15 * m.pitch)):
        spanned = {b for b in (_band_of(w, m.bands) for w in run) if b is not None}
        if len(spanned) >= 2 and len(run) >= 3:      # a group spanner, not a column caption
            continue
        for w in run:
            if w.bbox.x1 - w.bbox.x0 > m.pitch:      # too wide to belong to one column
                continue
            if _UNITS_TOKEN.search(w.text) or _NOTE_TOKEN.search(w.text):
                continue
            k = _band_of(w, m.bands)
            if k is not None:
                out.setdefault(k, []).append(w)
    return out


def _join_caption(parts: list[str]) -> str:
    """Join caption fragments, honouring the hyphen a printed column header wraps on
    ("Non-" / "controlling" / "interests" is one word plus two, not three)."""
    text = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if text and not text.endswith("-"):
            text += " "
        text += p
    return text.strip()


def _matrix_column_names(m: _Matrix) -> list[str] | None:
    """Name every component column from the header band, or None if that cannot be done.

    Returns None rather than a partial answer: a column we cannot name is a column whose figures
    we cannot attribute, and a made-up or duplicated name would silently merge two components.
    """
    per_row = [_caption_words(m.rows[i], m) for i in range(m.first_data)]
    # The header band is anchored by the rows that caption most columns at once (the last line
    # of the English captions, the Chinese line, the units line).
    anchor = [i for i, caps in enumerate(per_row)
              if len(caps) >= max(3, (len(m.bands) + 1) // 2)]
    if not anchor:
        return None
    start, end = min(anchor), max(anchor)
    # A three-line caption ("Share" / "premium" / "account") puts its first line ABOVE the row
    # that names every column, so extend upward through tightly spaced lines that caption
    # something — but no further, or the statement title and the group spanner join the names.
    while (start > 0 and per_row[start - 1]
           and _tight_below(_row_box(m.rows[start - 1]), _row_box(m.rows[start]))):
        start -= 1

    names: list[str] = []
    for k in range(len(m.bands)):
        words = [w for i in range(start, end + 1) for w in per_row[i].get(k, [])]
        latin = [w.text for w in words if re.search(r"[A-Za-z]", w.text)]
        # Prefer the English caption as the key; a Chinese-only filing keeps its own wording.
        name = _join_caption(latin) or _join_caption([w.text for w in words])
        if not name:
            return None
        names.append(name)
    return names if len(set(names)) == len(names) else None


def _heads_indented_block(words: list[Word]) -> bool:
    """A caption that HEADS the indented rows beneath it rather than wrapping into the next
    valued row — "Other comprehensive income/(loss) for the year:" and its CJK twin ending in
    the fullwidth colon. Gluing such a caption onto the first row below it corrupts that label.
    """
    if _looks_like_header(words):
        return True
    return " ".join(w.text for w in words).strip().endswith(("：", "﹕"))


def _matrix_basis(words: list[Word]) -> Basis:
    """One basis for the whole matrix. Its columns are components, so the Consolidated/Standalone
    banding used for comparatives would read them as bases and split the row apart."""
    text = " ".join(w.text for w in words)
    if _STANDALONE.search(text) and not _CONSOL.search(text):
        return Basis.STANDALONE
    return Basis.CONSOLIDATED


def _is_matrix_noise(label: str, row_text: str, vals: list) -> bool:
    """A running header / page footer / statement title whose stray year landed in a value column.

    Deliberately laxer than ``_is_noise_row`` in one respect: a period-only label is *not* noise
    here, because "At 1 January 2023" / "於二零二三年一月一日" IS the opening-balance movement
    row. Chrome is recognised instead from the whole printed line — the page footer's company
    name sits in the label column while its "Annual Report 2023" sits over the value columns.
    """
    if _RUNNING_HDR.search(row_text):
        return True
    if not vals or not all(_is_date_ish(v) for v in vals):
        return False
    return bool(_HDR_LABEL.search(label)) or _is_period_only_label(label)


def _matrix_items(m: _Matrix, names: list[str], *, page_index: int, document_id: str | None,
                  source_kind: str, ordinal_start: int, fmt=None,
                  unit_ctx: UnitContext | None = None, dims: tuple[str, ...] = (),
                  log=None) -> tuple[list[LineItem], int]:
    """One LineItem per MOVEMENT ROW, its values keyed by component-column name.

    Why one item per row rather than one per cell: ``LineItem.values`` is already a dict keyed by
    ``ValueKey(basis, period_end, period_label)``, so a single row holds as many named values as
    it has columns, and ``_serialize_rows`` ships ``period_label`` + ``period_display`` per value
    — the API and the statement view therefore render named component columns with no change
    downstream (``excel_extract`` already puts real column-header text in ``period_label``).
    One item per cell would multiply a 14-column statement into ~200 rows, destroy the row
    ordering the statement view relies on, and flood mapping with duplicate labels.

    The positional "current"/"prior" keys are deliberately NOT used: a component is not a period,
    and labelling it so would feed equity components into period-over-period arithmetic.
    """
    items: list[LineItem] = []
    ordinal = ordinal_start
    basis = _matrix_basis([w for row in m.rows for w in row])
    value_left = m.bands[0][0]
    pending: list[Word] = []                 # label lines waiting for the row that has figures
    tail: BBox | None = None                 # box of the LAST pending line, for the wrap test
    for i in range(m.first_data, len(m.rows)):
        row = m.rows[i]
        label_words = [w for w in row if _xc(w) <= value_left]
        cells = [w for w in _matrix_cells(row, fmt) if _band_of(w, m.bands) is not None]

        # A movement in equity always touches at least its component and a total column, so a
        # lone figure on a line is chrome (a page footer's year), not a row of the matrix.
        if len(cells) < 2 or _strong_cells(cells, fmt) * 2 < len(cells):
            # No amounts on this line. Either the first line of a wrapped movement caption, or
            # a footnote whose glyph-split digits fell in the columns (cells but no amounts).
            if cells or not label_words:
                pending, tail = [], None
                continue
            box = _row_box(label_words)
            # Only vertical adjacency is required: the label column of a matrix holds nothing
            # else, and a bilingual continuation line is indented to sit under the *Chinese*
            # caption ("十二月三十一日" beneath "於二零二三年"), so the left-edge test
            # ``_wrap_adjacent`` applies to a two-column face would reject a genuine wrap.
            if tail is not None and not _tight_below(tail, box):
                pending = []                       # not a continuation, a new block
            pending, tail = pending + label_words, box
            if _heads_indented_block(pending):
                pending, tail = [], None
            continue

        if tail is not None and not _tight_below(tail, _row_box(label_words or row)):
            pending = []
        label_words, pending, tail = pending + label_words, [], None
        label = _join_words(_regroup_scripts(label_words))
        if not label:
            continue
        vals = [d for d in (_num(_cell_text(w.text), fmt) for w in cells) if d is not None]
        if _is_matrix_noise(label, " ".join(w.text for w in row), vals):
            continue

        li = LineItem(source_label=label, ordinal=ordinal, role=LineRole.LINE,
                      source=ValueSource.MACHINE)
        label_bbox = _union([w.source_bbox for w in label_words])
        for cw in cells:
            # A nil dash is printed for "no movement"; it is not a figure, so no value is
            # emitted for it — the same reason the two-column path never invents a zero.
            dec = _num(_cell_text(cw.text), fmt)
            if dec is None:
                continue
            k = _band_of(cw, m.bands)
            prov = Provenance(
                document_id=document_id, page_index=page_index, bbox=cw.bbox,
                value_bbox=cw.bbox, label_bbox=label_bbox, text_snippet=label,
                source_kind=source_kind, producer=f"extract:{source_kind}@0.1.0",
            )
            store_fact(li, ExtractedValue(
                value_raw=dec, value=dec, basis=basis,
                # The component name is both the key and the column header shown in the UI.
                period_label=names[k], period_display=names[k],
                unit_ctx=unit_ctx or UnitContext(), provenance=prov,
            ), dims, log=log, where=f"page={page_index}:matrix:")
        if li.values:
            items.append(li)
            ordinal += 1
    return items, ordinal


def _maybe_matrix(words: list[Word], *, statement: str | None,
                  fmt=None) -> tuple[_Matrix | None, list[str] | None]:
    """Matrix geometry + column names for a matrix page, else (None, None).

    Skips the (re-)grouping entirely for pages that cannot be a matrix, so the two-column
    reconstruction of every other statement face costs exactly what it did before.
    """
    if statement != "changes_in_equity":
        numeric = sum(1 for w in words if _num(_cell_text(w.text), fmt) is not None
                      or _NIL_CELL.match(_cell_text(w.text)))
        if numeric < _MATRIX_MIN_COLS * _MATRIX_MIN_ROWS:
            return None, None
    m = _detect_matrix(_group_rows(words, _line_tol(words)), fmt)
    if m is None:
        return None, None
    return m, _matrix_column_names(m)


def build_line_items(words: list[Word], *, page_index: int, document_id: str | None,
                     source_kind: str, ordinal_start: int = 0,
                     number_format=None, statement: str | None = None,
                     log=None, scope: ScopeSelection | None = None,
                     normalisation: Normalisation | None = None,
                     on_face: bool = True) -> tuple[list[LineItem], int]:
    """Reconstruct line items from positioned words. Returns (items, next_ordinal).

    Both bases are extracted in one pass: a two-basis header band (Group | Company,
    Consolidated | Standalone — from ``scope_selection.entity_scope.signals``) attributes each
    value column to its basis, and within a basis the column HEADING DATE decides which period a
    column is (``scope_selection.period_selection``). ``number_format`` (a locale
    ``NumberFormat``) makes value parsing locale-correct; omit for the US default.

    ``statement`` is the page classifier's verdict; ``"changes_in_equity"`` selects the matrix
    path, which a matrix layout also selects on its own so a mis-classified page still parses.
    ``log`` (``ctx.log``) records why a matrix page was skipped or fell back, and every scope
    decision taken from the rulebook — which basis header was found, which column was read as the
    current period, the unit resolved for the statement, and each conflict that routed it to
    review.

    ``scope``/``normalisation`` override the rulebook in force (see :func:`in_force_rules`), and
    ``on_face`` says whether these rows are a statement FACE: the ``company_only_markers`` rule is
    declared about the face, and a note listing the Company's investments in subsidiaries must not
    relabel the basis of a note that belongs to the consolidated statements."""
    if scope is None or normalisation is None:
        in_force_scope, in_force_norm = in_force_rules()
        scope = scope if scope is not None else in_force_scope
        normalisation = normalisation if normalisation is not None else in_force_norm
    steps = _pipeline_steps(normalisation, scope)
    dims = guard_dimensions(scope)
    unit_signals = _unit_signals(scope)

    matrix, names = _maybe_matrix(words, statement=statement, fmt=number_format)
    if matrix is not None and names is not None:
        if log:
            log(f"extract:page={page_index}:equity_matrix_columns={len(names)}")
        # A matrix face declares its unit in its own header like any other statement, and
        # "persist unit on every fact" is not qualified by layout.
        return _matrix_items(matrix, names, page_index=page_index, document_id=document_id,
                             source_kind=source_kind, ordinal_start=ordinal_start,
                             fmt=number_format,
                             unit_ctx=_unit_context(_statement_unit(matrix.rows, unit_signals,
                                                                   number_format), page_index),
                             dims=dims, log=log)
    if statement == "changes_in_equity":
        # A named matrix we cannot attribute is worse than nothing: every figure would be filed
        # under a period that does not exist. Report it and emit no rows for the page. A page
        # with no matrix layout at all is a genuinely two-column equity statement (small
        # entities present one), so that one falls through to the normal reconstruction.
        if matrix is not None:
            if log:
                log(f"extract:page={page_index}:equity_matrix_unnamed_columns"
                    f"={len(matrix.bands)}(skipped)")
            return [], ordinal_start
        if log:
            log(f"extract:page={page_index}:equity_no_matrix_layout(two_column_path)")

    items: list[LineItem] = []
    ordinal = ordinal_start
    # The basis header is read from the UNMERGED rows: `_merge_wrapped_labels` glues a label-only
    # caption onto the next valued line, and a basis caption merged into the period line no longer
    # sits where it was printed — which defeats every geometric guard in `_basis_bands`.
    raw_rows = _group_rows(words)
    rows = _merge_wrapped_labels(raw_rows, number_format, steps)
    period_bands = _period_bands(raw_rows)      # real period-end dates for column headers, if any
    note_x = _detect_note_column(rows)          # x of the note-ref column, so it isn't read as a value
    # Where the value columns actually are. A first pass over the page's figures (after the note
    # column is removed, so note references never look like a column) so a row reporting only one
    # of two periods still files that figure under the period it is printed in.
    col_xs: list[list[tuple[float, str]]] = []
    for row in rows:
        _lw, _nr, _vw = _scan_row(row, number_format)
        _nr, _vw = _resolve_note_column(_nr, _vw, note_x, number_format)
        xs = [((w.bbox.x0 + w.bbox.x1) / 2, w.text) for w in _vw
              if _num(w.text, number_format) is not None]
        if xs:
            col_xs.append(xs)
    value_bands = _value_column_bands(col_xs)
    bands = _basis_bands(raw_rows, value_bands, _value_area(value_bands, col_xs),
                         signals=_entity_signals(scope), fmt=number_format,
                         log=log, page_index=page_index)
    if not bands and on_face:
        # company_only_markers: "Presence of …__investments_in_subsidiaries on the face is strong
        # evidence the column is company-only, since consolidation eliminates it." A single-basis
        # page carrying that line is the Company's statement, and filing it as the Group's adds
        # the Company's investment in its own subsidiaries to the consolidated balance sheet.
        stems = _company_only_stems(scope)
        for row in rows:
            lw, _nr, vw = _scan_row(row, number_format)
            if vw and _names_company_only(_join_words(lw), stems):
                # One band covers the page: `_basis_for` returns the nearest of one.
                bands = [(Basis.STANDALONE, 0.5)]
                if log:
                    log(f"extract:page={page_index}:entity_scope=company_only"
                        f"(marker:{_join_words(lw)!r})")
                break
    # units_and_currency: resolved from THIS statement's header (a page cannot see the cover), and
    # written onto every fact below rather than onto the document.
    unit = _statement_unit(raw_rows, unit_signals, number_format)
    factor = _conflict_factor(scope)
    if unit is not None and factor:
        clash = _scale_conflict(rows, factor, number_format, steps)
        if clash:
            # "Trust neither: route the statement to review." Dropping the unit is what makes that
            # visible downstream — a fact with no unit is not converted by anything.
            if log:
                log(f"extract:page={page_index}:units_conflict={clash}"
                    f"(header={unit[2]}):review")
            unit = None
    if unit is not None and log:
        log(f"extract:page={page_index}:units={unit[0] or 'unknown_ccy'}/{unit[2]}")
    unit_ctx = _unit_context(unit, page_index)
    # Group the value columns by basis (via the header band) once for the page, then let each
    # column's own heading date say which period it is.
    basis_cols: dict[Basis, list[int]] = {}
    for i, bx in enumerate(value_bands):
        basis_cols.setdefault(_basis_for(bx, bands), []).append(i)
    restated = _restated_markers(scope)
    col_periods = _column_periods(basis_cols, value_bands, period_bands, restated=restated,
                                  restated_cols=_restated_columns(raw_rows, value_bands, restated),
                                  log=log, page_index=page_index)
    section: str | None = None
    for row in rows:
        label_words, note_ref, value_words = _scan_row(row, number_format)
        note_ref, value_words = _resolve_note_column(note_ref, value_words, note_x, number_format)

        label = _join_words(_regroup_scripts(label_words))
        if not label or not value_words:
            # A label-only banner ("NON-CURRENT LIABILITIES", 流動負債) carries no amount, but it
            # scopes every row beneath it — the same caption under two banners is two different
            # concepts. Remember it before dropping the row.
            #
            # A sub-heading ending in a colon usually introduces a group WITHIN the section
            # rather than a new one, so by default it must not displace it: the rows under
            # "Adjustments for:" are still operating-activities rows, and losing that scope is
            # what lets an operating add-back resolve to an investing concept.
            #
            # Unless the sub-heading names a section in its own right. The income statement
            # splits both profit and total comprehensive income with "Attributable to:" /
            # "Total comprehensive income attributable to:", printing the same two captions
            # under each — so that colon heading is the only thing distinguishing them.
            #
            # A banner is recognised whatever its CASE. `_looks_like_header` accepts only
            # ALL-CAPS or a trailing colon, so a filing that prints "Non-operating expenses" in
            # title case set NO section at all — and the section gate then had nothing to tell
            # that section's captions apart from the ones printed identically elsewhere.
            #
            # A row that normalises to NOTHING is not a banner either: the units caption
            # ("RMB'000") and an audit-status note ("（未經審核）") are label-only rows that scope
            # no concept, and taking one as the section put a unit where a section belongs.
            caption = apply_pipeline(label, steps)
            banner = section_of_banner(caption)
            if label and caption and not value_words and (_looks_like_header(label_words, steps)
                                                          or banner is not None):
                if banner is not None or not _ends_with_colon(label, steps):
                    section = label
            continue

        # Drop running-header / statement-title / period-caption lines that leaked in as rows
        # (their only "value" is a date fragment) — never a genuine financial line.
        row_vals = [d for d in (_num(w.text, number_format) for w in value_words) if d is not None]
        if _is_noise_row(label, row_vals, steps):
            continue

        # A heading is often printed on the SAME line as its first figure, so it never appears as
        # a label-only row: "Total comprehensive loss attributable to: … Owners of the parent"
        # is one row carrying the owners' amount. The heading still scopes this row and the rows
        # under it — without that, the second "Non-controlling interests" of the income statement
        # stays under the profit split and is added to the first, which is meaningless.
        head = re.split(r"[:：]", label)[0] if re.search(r"[:：]", label) else ""
        if head and section_of_banner(head) is not None:
            section = head.strip()

        li = LineItem(source_label=label, ordinal=ordinal, role=LineRole.LINE,
                      section_hint=section, source=ValueSource.MACHINE)
        label_bbox = _union([w.source_bbox for w in label_words])
        # Place each value in its own column within its basis — by the column's period when the
        # page has columns, else by the order the figures are printed in.
        per_basis: dict[Basis, int] = {}
        # Once the page's value columns are known, a figure that sits under NONE of them is not
        # a figure: it is a note reference the note-column heuristics did not catch, printed in
        # its own narrow column to the left. Taken as a value it claims the current period and
        # displaces the row's real figures. Only dropped when the row has at least one figure
        # that IS under a column, so a row the bands do not describe still reports positionally.
        in_col = {id(w): _column_index((w.bbox.x0 + w.bbox.x1) / 2, value_bands)
                  for w in value_words}
        drop_outliers = bool(value_bands) and any(v is not None for v in in_col.values())
        for vw in sorted(value_words, key=lambda w: w.bbox.x0):
            dec = _num(vw.text, number_format)
            if dec is None:
                continue
            if drop_outliers and in_col[id(vw)] is None:
                continue
            xc = (vw.bbox.x0 + vw.bbox.x1) / 2
            basis = _basis_for(xc, bands)
            # The column this figure is printed in decides its period, and the column's HEADING
            # decides which period that is. Order is the fallback for a page with no columnar
            # structure, and for a figure that sits under no column.
            k = per_basis.get(basis, 0)
            col = _column_index(xc, value_bands)
            if col is not None and col in basis_cols.get(basis, []):
                k = basis_cols[basis].index(col)
            per_basis[basis] = max(per_basis.get(basis, 0), k) + 1
            period_label = col_periods.get(
                (basis, col) if col is not None else (basis, -1),
                "current" if k == 0 else "prior" if k == 1 else f"col{k}")
            prov = Provenance(
                document_id=document_id, page_index=page_index, bbox=vw.source_bbox,
                value_bbox=vw.source_bbox, label_bbox=label_bbox, text_snippet=label,
                source_kind=source_kind, producer=f"extract:{source_kind}@0.1.0",
            )
            store_fact(li, ExtractedValue(
                value_raw=dec, value=dec, basis=basis,
                period_label=period_label,
                period_display=_period_for(xc, period_bands),  # display-only date, if detected
                unit_ctx=unit_ctx, provenance=prov,
            ), dims, log=log, where=f"page={page_index}:")
        if note_ref:
            li.note_refs.append(NoteRef(raw=note_ref, numbers=[note_ref]))
            li.note_number = note_ref
        items.append(li)
        ordinal += 1
    return items, ordinal


def _union(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    b = boxes[0]
    for o in boxes[1:]:
        b = b.union(o)
    return b

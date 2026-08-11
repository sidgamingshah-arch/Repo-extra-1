"""Residual routing — a printed face line never disappears.

A statement is a complete document: every line the filing prints on the face of the balance
sheet, income statement or cash flow statement contributes to that section's subtotal, and the
subtotal to the statement's total. So an extracted face line that matched no specific concept
cannot simply be dropped — doing that silently removes real money from the statement and the
subtotals stop tying. It belongs in its own section's residual bucket ("Others"), which is what
that bucket is for.

Placing a line in the right section is the whole problem, and the statement's own structure
answers it: **a section runs up to its subtotal**. "Trade and bills payables" through to "Total
current liabilities" are the current liabilities; whatever is printed between the previous
subtotal and the next one belongs to the next one's section. That works where banners do not —
the income statement prints no section banners at all, and a cash flow continuation page often
shows only a truncated running header.

Three signals are used, strongest first:

1. the section banner above the row, when it names a section we know (``section_hint``);
2. the next section subtotal at a higher ordinal — the accounting structure above;
3. the section of the nearest preceding mapped line, for a trailing row after the last subtotal.

Rows deliberately NOT routed: anything that is itself a subtotal or total (it would be counted
twice), note detail (only the face is being completed), and rows with no value at all.

Whether the routing is *correct* is not a matter of opinion: once residuals are in place, each
section subtotal must equal the sum of its children. The structural stage checks exactly that
relation, so a mistake here shows up as a failing rollup rather than as a plausible-looking
number.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.models.enums import LineRole
from app.core.stage import PipelineContext
from app.services.mapping import section_of_banner, section_of_key

# How a residual assignment is recorded on the line, so the review queue and the statement
# inspector can both say the figure was combined rather than identified.
FALLBACK_ALLOC = "fallback_combined"


def _sections_from_template(template_def: dict) -> dict[str, list[tuple[str, str, str]]]:
    """Per statement type, the sections in printed order as (section_token, subtotal_key,
    others_key). A section with no residual bucket is skipped — there is nowhere to put a line.
    """
    out: dict[str, list[tuple[str, str, str]]] = {}
    for st in (template_def or {}).get("statements", []):
        rows: list[tuple[str, str, str]] = []
        for sec in st.get("sections", []):
            kids = [c for c in sec.get("children", []) if c.get("canonical_key")]
            if not kids:
                continue
            others = next((c["canonical_key"] for c in kids
                           if c["canonical_key"].endswith("__others")), None)
            subtotal = next((c["canonical_key"] for c in kids
                             if c.get("role") in ("subtotal", "total")), None)
            if not others:
                continue
            # The token between the statement prefix and "__" is the section namespace
            # ("bs_current_liabilities__others" -> "current_liabilities").
            token = others.split("__", 1)[0].split("_", 1)[1]
            rows.append((token, subtotal or "", others))
        if rows:
            out[st.get("type", "")] = rows
    return out


class ResidualStage:
    name = "residual"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        template = getattr(ctx, "template_def", None) or getattr(ctx, "template", None)
        if hasattr(template, "model_dump"):
            template = template.model_dump(mode="json")
        sections = _sections_from_template(template or {})
        if not sections or not doc.line_items:
            ctx.log("residual:skipped(no template sections or no line items)")
            return doc

        stmt_by_page = {p.index: p.statement for p in doc.pages if p.statement}

        def statement_of(li) -> str | None:
            for ev in li.values.values():
                if ev.provenance is not None:
                    return stmt_by_page.get(ev.provenance.page_index)
            return None

        def has_value(li) -> bool:
            return any(ev.value is not None or ev.value_raw is not None
                       for ev in li.values.values())

        # A statement ends at its closing total ("Cash and cash equivalents at end of year",
        # "Total equity and liabilities"). Whatever is printed below that is narrative — the note
        # on what cash equivalents comprise, a signature block — and it arrives as rows because it
        # carries figures. Routing prose into a section's bucket corrupts that section's subtotal
        # by whatever the sentence happened to contain, so the statement's own end is the cutoff.
        # Statement-level totals are the template's section-level nodes: canonical keys with no
        # "__" section namespace.
        closing: dict[str, int] = {}
        for st in (template or {}).get("statements", []):
            keys = {sec.get("canonical_key") for sec in st.get("sections", [])
                    if sec.get("canonical_key") and "__" not in sec["canonical_key"]}
            last = max((li.ordinal for li in doc.line_items if li.canonical_key in keys),
                       default=None)
            if last is not None:
                closing[st.get("type", "")] = last

        ordered = sorted(doc.line_items, key=lambda li: li.ordinal)
        routed = skipped_after_end = 0
        for idx, li in enumerate(ordered):
            # ``doc.line_items`` is the FACE of the statements; note detail lives in
            # ``doc.notes`` as NoteItems, so there is nothing to exclude on that basis here.
            # (Do not filter on ``note_number``: reconstruction sets it on a face row that
            # merely CITES a note, which is most of them.)
            if li.canonical_key:
                continue
            if li.role in (LineRole.SUBTOTAL, LineRole.TOTAL) or not has_value(li):
                continue
            stmt = statement_of(li)
            secs = sections.get(stmt or "")
            if not secs:
                continue
            end = closing.get(stmt or "")
            if end is not None and li.ordinal > end:
                skipped_after_end += 1
                continue
            by_token = {tok: others for tok, _, others in secs}
            subtotal_to_token = {sub: tok for tok, sub, _ in secs if sub}

            target = None
            # 1. the banner printed above this row
            if li.section_hint:
                tok = section_of_banner(li.section_hint)
                if tok and tok in by_token:
                    target = by_token[tok]
            # 2. the next section subtotal below it — a section runs up to its subtotal
            if target is None:
                for nxt in ordered[idx + 1:]:
                    tok = subtotal_to_token.get(nxt.canonical_key or "")
                    if tok:
                        target = by_token.get(tok)
                        break
            # 3. a trailing row after the last subtotal keeps the section above it
            if target is None:
                for prev in reversed(ordered[:idx]):
                    tok = section_of_key(prev.canonical_key or "")
                    if tok and tok in by_token:
                        target = by_token[tok]
                        break
            if target is None:
                continue

            li.canonical_key = target
            li.confidence.mapping = min(li.confidence.mapping or 0.5, 0.5)
            li.confidence.method = "residual"
            li.confidence.flags.append(f"alloc:{FALLBACK_ALLOC}")
            # Routed, not identified — it stays visible in review so an analyst can promote it
            # to a specific concept (or add an alias) rather than accept the bucket.
            li.confidence.flags.append("residual_combined")
            routed += 1

        ctx.log(f"residual:routed={routed} after_statement_end={skipped_after_end} "
                f"unmapped_remaining={sum(1 for li in doc.line_items if not li.canonical_key)}")
        return doc

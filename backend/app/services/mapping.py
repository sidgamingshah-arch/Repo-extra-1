"""Ontology mapping — a combination of methods, with the LLM as the key driver.

Mapping a printed source line to a canonical template concept is done by **meaning**,
not string similarity — but as an *ensemble*: every method contributes and they
corroborate one another. No single methodology is forced out.

1. exact / normalized lexical  (free, unambiguous → short-circuits)
2. rule-based                  (regex / keyword hints, minus exclude hints)
3. similarity / fuzzy          (rapidfuzz — candidate evidence + shortlist)
4. semantic embeddings         (cosine similarity — candidate evidence + shortlist)
5. **LLM semantic decision**   (the key driver): shown each candidate's criteria
   (definition, include/exclude, confusable-with, value_scope) plus the ontology's global
   policies + worked examples, it chooses by meaning — so "Amounts due from customers",
   "Receivables from clients" and "Trade debtors" all resolve to ``trade_receivables``
   with no lexical alias hit.

Combination policy: exact wins outright; otherwise the LLM decides but is corroborated by
the deterministic methods — agreement raises confidence, a strong lexical disagreement
lowers it and flags review (the agreeing methods are recorded). When no LLM is configured
(``extraction.llm_mapping=false`` or provider ``stub``) or it abstains, the deterministic
ensemble decides with a margin-over-runner-up accept. Each value also carries an
``allocation_status`` so parent/child/residual handling stays auditable. Winning method,
confidence and per-strategy scores are recorded.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

from app.config import Settings, get_settings
from app.core.models.enums import MappingMethod
from app.schemas.ontology import OntologyDefinition, OntologyMapping
from app.services.han import has_han, to_simplified


class LlmMappingDecision(BaseModel):
    """Structured output for a single description-based mapping decision."""

    canonical_key: str = Field(description="the chosen canonical key, or \"\" if none fits")
    confidence: float = Field(ge=0, le=1)
    allocation_status: str = Field(
        default="",
        description="how the value relates to others: direct_exclusive | child_component | "
                    "parent_gross_evidence_only | calculated_residual | fallback_combined | unmapped_review",
    )
    reason: str = Field(default="", description="brief justification grounded in meaning/criteria")


class LlmBatchItem(BaseModel):
    item_id: str
    canonical_key: str = Field(description="chosen key, or \"\" if none fits")
    confidence: float = Field(ge=0, le=1)
    allocation_status: str = ""


class LlmBatchDecision(BaseModel):
    """Per-statement decision over many captions at once, so cross-line judgements
    (parent/child containment, residualisation, 'Others') have full context."""

    mappings: list[LlmBatchItem] = Field(default_factory=list)


_LLM_SYSTEM = (
    "You map a single raw line-item caption from a financial statement to ONE canonical "
    "concept, by MEANING. You are given the caption (with any context) and candidate "
    "concepts, each with: canonical_key, a definition, inclusion criteria (include), "
    "exclusion criteria (exclude), concepts it is easily confused with, and its value_scope. "
    "Choose the candidate whose definition and criteria best match what the caption "
    "represents — rely on financial meaning, not string similarity or shared words. Respect "
    "the exclusion criteria and the confusable-with warnings. If no candidate genuinely "
    "fits, return an empty canonical_key. Return calibrated confidence in [0,1] (high only "
    "when unambiguous) and, when clear, an allocation_status describing how the value "
    "relates to parents/children."
)

# Appended for the BATCH path only. The base instruction opens "You map a single raw line-item
# caption", which is false when several are decided at once, and it never says what a section is —
# so a model told an item's section had no way to know the word was binding. Kept separate from
# `_LLM_SYSTEM` so correcting the batch framing cannot silently rewrite the per-line prompt.
_LLM_BATCH_ADDENDUM = (
    "\n\nThis request carries SEVERAL captions from one statement at once, in the order they are "
    "printed in the document. Decide them together: a caption's meaning is often fixed by the "
    "lines around it — a parent and the children that make it up, a subtotal and the lines above "
    "it, a residual 'Others' that is whatever the section's named lines do not account for.\n"
    "An item may carry a `section`: the normalised heading it was printed under (for example "
    "`current_assets`, `equity`, `current_liabilities`). It is BINDING — choose a concept whose "
    "canonical_key belongs to that section. It is what separates captions the document prints "
    "identically in more than one place: an 'Others' line, or the 'Non-controlling interests' "
    "printed once under the profit split and again under the total-comprehensive split. An item "
    "with no `section` is unconstrained: decide it on meaning alone.\n"
    "Return one entry per item_id you were given, and never an item_id that was not given to you."
)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0 for a zero or mismatched vector."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = sum(x * x for x in a[:n]) ** 0.5
    nb = sum(x * x for x in b[:n]) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def normalize_label(text: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace (locale-agnostic).

    Han text is folded to Simplified so a Traditional caption from a Hong Kong or Taiwan
    filing compares equal to a Simplified alias (and vice versa) — the same concept printed
    in the other script would otherwise never match.
    """
    text = to_simplified(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# A bilingual filing prints one caption in both scripts: "REVENUE 收益",
# "Cost of sales 銷售成本". Matching the concatenation dilutes every score (half the string is
# always "wrong" for a single-language alias), so each script's run is also matched on its own
# and the best segment wins.
_HAN_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+(?:\s*[㐀-䶿一-鿿豈-﫿]+)*")


def label_segments(text: str) -> list[str]:
    """The caption plus its per-script halves (Latin-only and Han-only), longest first.

    Returns just ``[text]`` for a single-script caption, so monolingual filings are unaffected.
    """
    if not text or not has_han(text):
        return [text]
    han = " ".join(_HAN_RUN.findall(text)).strip()
    latin = _HAN_RUN.sub(" ", text)
    latin = re.sub(r"\s+", " ", latin).strip()
    out = [text] + [p for p in (latin, han) if p and p != text]
    return list(dict.fromkeys(out))


@dataclass
class Candidate:
    canonical_key: str
    method: MappingMethod
    score: float
    allocation_status: str | None = None
    # Set when the concept whose evidence matched is NOT the one being proposed: the caption
    # matched one leaf of a collision family and the banner named another. Carried so the decision
    # stays auditable instead of looking like an ordinary hit on the concept it was corrected to.
    rerouted_from: str | None = None


@dataclass
class MappingResult:
    canonical_key: str | None
    method: MappingMethod
    confidence: float
    candidates: list[Candidate] = field(default_factory=list)
    needs_review: bool = False
    scores: dict[str, float] = field(default_factory=dict)  # per-strategy best score
    allocation_status: str | None = None                    # how the value was derived
    agreement: list[str] = field(default_factory=list)      # methods that corroborated the pick
    rerouted_from: str | None = None                        # see Candidate.rerouted_from


# Canonical keys are namespaced by statement SECTION as well as by statement
# (bs_non_current_liabilities__…, bs_current_assets__…), and a statement prints the same caption
# under two of them: "Interest-bearing bank and other borrowings" appears once under non-current
# liabilities and once under current, as do senior notes and lease liabilities. The caption
# cannot distinguish them; the banner above the row can. Each entry maps a section token found in
# a key to the words a banner uses for it, in English and in Han (folded to Simplified by
# ``normalize_label``).
#
# Module-level, and free of any ontology: the vocabulary is a property of how statements are
# printed, and other stages need to read a banner without paying to build a matcher.
SECTION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Longest first: "non current liabilities" must not be read as "current liabilities".
    ("non_current_liabilities", ("non current liabilities", "noncurrent liabilities",
                                "非流动负债", "长期负债")),
    ("non_current_assets", ("non current assets", "noncurrent assets",
                           "非流动资产", "长期资产")),
    ("current_liabilities", ("current liabilities", "流动负债")),
    ("current_assets", ("current assets", "流动资产")),
    ("equity", ("equity", "capital and reserves", "权益", "股本及储备", "资本及储备")),
    # The cash flow statement is namespaced the same way, and its captions repeat across
    # activities: "Interest received" and "Dividends received" appear under both operating and
    # investing, "Acquisition of subsidiaries" under investing and financing.
    ("cash_flow_from_operating_activities", ("operating activities", "经营活动", "营运活动")),
    ("cash_flow_from_investing_activities", ("investing activities", "投资活动")),
    ("cash_flow_from_financing_activities", ("financing activities", "融资活动", "筹资活动")),
    # The income statement ends with the SAME two captions twice — "Owners of the parent" and
    # "Non-controlling interests" — once splitting profit for the year and once splitting total
    # comprehensive income. Only the sub-heading above them tells the pairs apart; without it
    # both land on one concept and are added into a meaningless total. The comprehensive-income
    # heading is tested first because it contains "attributable to" as well.
    # "comprehensive" is the whole distinction, and it has to be matched on its own: a filing
    # reporting a loss prints "Total comprehensive LOSS attributable to", and a filing covering
    # both prints "income/(loss)". Requiring the word "income" missed every one of those, which
    # sent the comprehensive-income split into the profit split — the exact collapse this entry
    # exists to prevent. The profit split never says "comprehensive".
    ("total_comprehensive_income_attributable_to", ("comprehensive", "全面收", "全面亏")),
    ("profit_attributable_to",
     ("profit attributable", "loss attributable", "attributable to",
      "溢利归属", "亏损归属", "应占溢利")),
    # The income statement's ordinary sections. Absent until now, which meant `section_of_key`
    # returned None for every `pl_income__*`, `pl_expenses__*`, `pl_non_operating_expenses__*`,
    # `pl_exceptional_items__*` and `pl_tax_expense__*` key — 34 of the 173 shipped concepts — so
    # `_in_section` waved all of them through and a banner like "REVENUE" was captured as a
    # section_hint that normalised to nothing. The two attributable-to families above were the
    # only part of the P&L a banner could scope.
    #
    # ORDER IS LOAD-BEARING TWICE OVER. `section_of_key` matches "_<tok>__" as a substring, and
    # "_non_operating_expenses__" CONTAINS "_expenses__" — so the compound must be tested first,
    # exactly as non_current_liabilities is tested before current_liabilities. And
    # `section_of_banner` returns the first match, so "Income tax expense" must reach tax_expense
    # before it can reach income.
    ("non_operating_expenses", ("non operating", "nonoperating", "非经营", "非营运")),
    ("exceptional_items", ("exceptional", "非经常性", "特殊项目")),
    # "income tax" is deliberately absent: it is contained in three BALANCE-SHEET captions the
    # ontology maps as their own concepts — deferred income tax assets, prepaid income tax, income
    # tax payable — and any of those reaching this function as a banner would scope the row to
    # tax_expense and refuse every bs_ concept under it. "Income tax expense" still resolves here,
    # via "tax expense".
    ("tax_expense", ("tax expense", "taxation", "税项", "所得税")),
    ("expenses", ("expenses", "开支", "费用")),
    # Deliberately NOT the bare words "income" / "收入": a banner naming the income section says
    # revenue or turnover, while "income" appears in captions all over a filing (deferred income
    # tax, other comprehensive income). A banner that resolves to the WRONG section is worse than
    # one that resolves to nothing, because the gate then refuses the correct concept.
    ("income", ("revenue", "turnover", "营业额", "营业收入", "收益")),
)


def section_of_banner(text: str | None) -> str | None:
    """The section a banner names, or None when it names none we recognise.

    An umbrella banner that spans more than one section ("EQUITY AND LIABILITIES", which IFRS
    statements print above the Equity / Non-current / Current sub-banners) scopes nothing on its
    own: reading it as "equity" would refuse every liability concept beneath it. Those return
    None so the constraint simply does not apply.
    """
    if not text:
        return None
    folded = normalize_label(text)
    if ("equity" in folded or "权益" in folded) and ("liabilit" in folded or "负债" in folded):
        return None
    for token, words in SECTION_WORDS:
        if any(w in folded for w in words):
            return token
    return None


def section_of_key(canonical_key: str) -> str | None:
    """The section namespace a canonical key sits in, or None for a key that has none
    (``bs_total_assets``, ``pl_profit_before_tax``). Matched longest-first, since
    "bs_non_current_liabilities__x" also contains "_current_liabilities__".
    """
    return next((tok for tok, _ in SECTION_WORDS if f"_{tok}__" in canonical_key), None)


# Vocabularies a caption can name only ONE member of. IAS 7 divides cash flows into exactly three
# activities and a statement labels each subtotal with its own, so a caption saying "financing
# activities" is not the investing subtotal under any reading.
#
# This is not a similarity judgement the fuzzy scorer may trade off. "Net cash used in investing
# activities" and "Net cash flows used in financing activities" differ by one word in seven, which
# token similarity scores at 0.92 — above any threshold anyone would pick. The consequence is
# silent and expensive: the financing figure is filed under investing, investing then shows two
# figures summed, and the financing line has none. The structural check catches the arithmetic
# afterwards, but the caption said which line it was all along.
#
# Add a vocabulary here only when naming one member genuinely rules out the others for every
# filing — this gate cannot be overridden by evidence, so a merely-usually-true grouping would
# refuse correct mappings.
EXCLUSIVE_VOCABULARIES: tuple[tuple[str, ...], ...] = (
    ("operating", "investing", "financing"),
)
_WORD = {w: re.compile(rf"\b{w}\b", re.IGNORECASE)
         for vocab in EXCLUSIVE_VOCABULARIES for w in vocab}


def _names_a_different_class(canonical_key: str, caption: str) -> bool:
    """Whether the caption names a member of an exclusive vocabulary that the concept is not in.

    Read off the canonical key, so it needs no ontology authoring and holds for any template that
    names its sections after the thing they contain
    (``cf_cash_flow_from_investing_activities__…``).
    """
    key = (canonical_key or "").lower()
    for vocab in EXCLUSIVE_VOCABULARIES:
        in_key = [w for w in vocab if w in key]
        if len(in_key) != 1:
            continue                      # the concept is not in this vocabulary, or is ambiguous
        in_caption = [w for w in vocab if _WORD[w].search(caption)]
        # Only refuse when the caption names exactly one member and it is not the concept's own.
        # A caption naming two ("cash flows from operating and investing activities") is a genuine
        # combined line and is left to the ordinary tiers to judge.
        if len(in_caption) == 1 and in_caption[0] != in_key[0]:
            return True
    return False


# Concepts that a statement prints under ONE caption and that differ only in which section
# variant of the same fact they are. The banner above the row is the only evidence that separates
# them, so when a decision names the right kind of thing and the wrong variant the banner settles
# it: the answer is corrected to the sibling the banner names instead of being discarded. Discarding
# it drops the row to a weaker path, and for the P&L bottom line that loses the largest figure on
# the statement — a wrapped bilingual "TOTAL COMPREHENSIVE / LOSS FOR THE YEAR" reaches the matcher
# as the bare fragment "LOSS FOR THE YEAR", which is an alias of the OTHER bottom line.
#
# These are declared here and not read out of the rulebook, which is a compromise worth naming.
# The v2 ontology describes every one of these collisions — `section_disambiguation` prose on 18
# concepts, and `binding.order` step 6 nominating mutual `confusable_with` as the tie set — but
# neither is usable as the declaration:
#   * `confusable_with` is a confusion graph, not a family. Its mutual pairs connect into a single
#     47-concept component in the shipped file (share capital → reserves → NCI → the tax lines →
#     both bottom lines), so re-routing anywhere inside it would move an answer between concepts
#     that are different facts — the opposite of conservative.
#   * `section_disambiguation` is free-form prose, and only some of it names the sibling's key at
#     all. Scraping keys out of it would make a wording edit a behaviour change, and prose cannot
#     be told apart from "never confuse this with that", which means the opposite.
# A typed family block on the schema is the right home; see the integrator note. Until it exists,
# a rulebook that does not contain these keys simply has no families and nothing re-routes.
CONCEPT_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lease_liability", ("bs_current_liabilities__current_lease_liabilities",
                         "bs_non_current_liabilities__non_current_lease_liabilities")),
    ("borrowings", ("bs_current_liabilities__current_borrowings",
                    "bs_non_current_liabilities__non_current_borrowings")),
    # Notes payable only. Bonds payable was in this family and had to come out: the template has no
    # current-bonds node, so "CURRENT LIABILITIES" identified exactly one leaf — current NOTES
    # payable — and a row printed "Bonds payable" was re-routed onto a different instrument at
    # confidence 1.0, replacing an honest residual with a specific wrong line that the subtotal
    # still ties to. A bond is not a note in the wrong section.
    ("notes_payable", ("bs_current_liabilities__cuurent_notes_payable",
                       "bs_non_current_liabilities__non_current_notes_payable")),
    ("properties_under_development", ("bs_current_assets__properties_under_development",
                                      "bs_non_current_assets__properties_under_development")),
    # HKAS 7.31 permits interest received in either activity, so the printed section is the whole
    # answer and the caption is byte-identical in both.
    ("interest_received", ("cf_cash_flow_from_operating_activities__interest_received",
                           "cf_cash_flow_from_investing_activities__interest_received")),
    ("nci_attribution", (
        "bs_equity__non_controlling_interests",
        "pl_profit_attributable_to__non_controlling_interests",
        "pl_total_comprehensive_income_attributable_to__non_controlling_interests",
    )),
    ("owners_of_parent", ("pl_profit_attributable_to__owners_of_the_parent",
                          "pl_total_comprehensive_income_attributable_to__owners_of_the_parent")),
    ("pl_bottom_line", ("pl_profit_for_the_year",
                        "pl_total_comprehensive_income_for_the_year")),
)

# The bottom-line pair is the one family whose leaves carry NO section namespace, so it cannot be
# identified by `section_of_key` and cannot lean on the same-thing rule below. It gets its own
# banner test, and that test has to be far narrower than the section vocabulary.
#
# `SECTION_WORDS` identifies the comprehensive-income SECTION by the bare word "comprehensive",
# deliberately, so that "comprehensive loss" and "income/(loss)" both match. Reusing it here fired
# the re-route on "STATEMENT OF COMPREHENSIVE INCOME" — an ordinary HKEX page title, captured as the
# section_hint for every row on the page. "Profit for the year" was filed as total comprehensive
# income at confidence 1.0, two different figures collapsed onto one concept, and
# pl_profit_for_the_year was left empty. Nothing downstream sees it: the subtotals still tie.
#
# So the evidence required is the word TOTAL bound to "comprehensive" — the wording a filing uses
# for the line ITSELF, not for the statement it appears in — and never the attribution sub-heading,
# which introduces the owners/NCI split rather than the bottom line.
_TCI_BOTTOM_LINE = re.compile(r"total\s+comprehensive|全面(?:亏损|虧損|收益|收入|损益)?\s*总?總?额")
_ATTRIBUTION = re.compile(r"attributable|归属|歸屬")


def _names_the_comprehensive_bottom_line(banner: str | None) -> bool:
    if not banner:
        return False
    folded = normalize_label(banner)
    return bool(_TCI_BOTTOM_LINE.search(folded)) and not _ATTRIBUTION.search(folded)

_FAMILY_MEMBERS: dict[str, tuple[str, ...]] = {
    key: members for _name, members in CONCEPT_FAMILIES for key in members
}

# The words that distinguish one SECTION VARIANT of a concept from another. Stripping them leaves
# the thing itself, which is what two members of a family must have in common. ("cuurent" is a typo
# retained in a shipped canonical key — keys are load-bearing, so it is matched rather than fixed.)
_VARIANT_PREFIX = re.compile(r"^(non[_-]?current|current|cuurent)_")


def _the_thing_itself(canonical_key: str) -> str | None:
    """What a key is ABOUT, with its section namespace and current/non-current wording removed.

    None for a key carrying no section namespace at all: such a key names a statement-level figure,
    and a statement-level figure has no section variant to be confused with.
    """
    _, sep, leaf = canonical_key.partition("__")
    if not sep:
        return None
    return _VARIANT_PREFIX.sub("", leaf)


def _is_variant_of(a: str, b: str) -> bool:
    """Whether two keys are the SAME THING in different sections.

    This is the whole licence for re-routing. A variant pair is one concept the filing may print in
    either of two sections — current vs non-current lease liabilities, interest received under
    operating vs investing — where the banner is the only evidence and the caption is often
    byte-identical. Anything else is a different concept that merely resembles its sibling, and
    "correcting" a decision onto it replaces a defensible answer with a confident wrong one:
    bonds payable is not notes payable, deferred revenue is not deferred income, and profit for the
    year is not total comprehensive income. Each of those was declared as a family and each produced
    a wrong figure that the subtotal checks could not see, because nothing was arithmetically
    inconsistent — only wrong.
    """
    ta, tb = _the_thing_itself(a), _the_thing_itself(b)
    return ta is not None and ta == tb


def family_leaf_named_by(canonical_key: str, banner: str | None) -> str | None:
    """The sibling of ``canonical_key`` that ``banner`` identifies, or None.

    None whenever the banner settles nothing — the key is in no family, the banner names no section
    we recognise, that section identifies no leaf, or it identifies more than one — and None when
    the leaf it identifies is the key itself, because then there is nothing to correct. Every one of
    those is a refusal to guess: this function is the only thing that may overrule a decision, so it
    answers only where the answer is forced.
    """
    members = _FAMILY_MEMBERS.get(canonical_key)
    if not members:
        return None
    # The bottom-line pair, on its own narrow evidence. Only one direction is answerable: a banner
    # can say "this line IS the total comprehensive one", but no banner says "this line is merely
    # profit", so a caption already mapped to the comprehensive line is never moved off it.
    if canonical_key == "pl_profit_for_the_year":
        return ("pl_total_comprehensive_income_for_the_year"
                if _names_the_comprehensive_bottom_line(banner) else None)
    if canonical_key == "pl_total_comprehensive_income_for_the_year":
        return None
    want = section_of_banner(banner)
    if not want:
        return None
    named = [k for k in members if section_of_key(k) == want]
    if len(named) != 1 or named[0] == canonical_key:
        return None
    # Last gate, and the one that does not depend on the declaration being right: re-route only
    # between two spellings of the same thing.
    if not _is_variant_of(canonical_key, named[0]):
        return None
    return named[0]


class OntologyMatcher:
    """Runs the ensemble for one ontology + locale."""

    def __init__(
        self,
        ontology: OntologyDefinition,
        locale: str | None = None,
        settings: Settings | None = None,
        embedding_provider=None,
        llm_provider=None,
    ):
        self.ontology = ontology
        self.locale = locale or ontology.locale
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider
        self.llm_provider = llm_provider
        # Description-based LLM mapping is the primary strategy when a provider is present
        # and not disabled in config.
        self.llm_enabled = bool(llm_provider) and self.settings.extraction.llm_mapping
        # Token/usage accounting for the audit log (read by the mapping stage).
        # `failures`/`last_error` exist so a run whose LLM calls all failed can report itself
        # as deterministic (what it actually was) instead of as LLM-mapped.
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "model": "",
                      "failures": 0, "last_error": "",
                      # Batch decisions thrown away, counted so the cost of the batch path is
                      # measurable: ids we never asked about, and answers the scoping gate
                      # refused. Both used to vanish on a bare `continue`.
                      "batch_unknown_ids": 0, "batch_refused": 0,
                      # Wrong-variant answers the banner corrected instead of discarding, and the
                      # distinct routes taken. A silent correction is worse than a refusal: it puts
                      # a figure on a different line of the face with nothing to point at.
                      "family_resolved": 0, "family_routes": []}
        # System prompt = the base instruction + the ontology's own extraction policies and
        # worked examples, so the LLM follows one consistent, auditable rulebook.
        self._system = self._build_system()
        # The batch path decides many captions at once and is told each row's section, neither of
        # which the base instruction describes. Additive, so the per-line prompt is unchanged.
        self._batch_system = self._system + _LLM_BATCH_ADDENDUM

        # Precompute normalized alias → key index for exact/fuzzy tiers, and a concept
        # index (key → mapping) for description lookups.
        # alias → EVERY concept that claims it. Two sections legitimately share a caption:
        # "Owners of the parent" and "Non-controlling interests" appear under both the profit
        # split and the comprehensive-income split, and "Others" appears in every section. Keeping
        # one key per alias made the section-appropriate concept unreachable — the caption
        # resolved to the wrong section's concept, was refused by the section gate, and the row
        # ended up unmapped even though its concept existed.
        self._alias_index: dict[str, list[str]] = {}
        self._alias_by_key: dict[str, list[str]] = {}
        self._by_key: dict[str, OntologyMapping] = {}
        # Alias embeddings, indexed by canonical key — computed lazily on first embedding use.
        self._alias_vecs: list[tuple[str, list[float]]] | None = None
        # Concepts a v2 rulebook declares unreachable by MATCHING: the section "Others" buckets,
        # populated by the residual sweep alone (a section's parent minus its confirmed children).
        # Keyed on `alias_matching` alone, not on the conjunction with match_priority 0 /
        # exclusive_residual / never_sweep that the shipped file also carries, because that field is
        # the declared switch and a conjunction lets one omitted field silently unlock a bucket.
        # Locking matters because a residual's caption is the most attractive one in the ontology:
        # "Others" fuzzy-matches almost anything short, and a model offered a bucket will use it for
        # a row it cannot place. Either way the figure lands in the bucket that is supposed to be
        # the section's *unexplained* remainder, and the reconciliation that would have reported the
        # gap now ties. The sweep still assigns them — it reads the template, not this index.
        self._locked: set[str] = {m.canonical_key for m in ontology.mappings
                                  if m.alias_matching == "disabled"}
        for m in ontology.mappings:
            self._by_key[m.canonical_key] = m
            if m.canonical_key in self._locked:
                continue
            # Index EVERY locale's aliases, not just the document's. A bilingual filing prints
            # both scripts on the same line, so restricting the index to the detected locale
            # makes a Chinese-only caption unmatchable in a document detected as English.
            # Recognising the printed text is locale-independent; the locale still orders
            # `aliases_for` for display/scoring preference.
            aliases = list(dict.fromkeys(
                m.aliases_for(self.locale)
                + [a for locale_aliases in m.aliases_i18n.values() for a in locale_aliases]
            ))
            self._alias_by_key[m.canonical_key] = [normalize_label(a) for a in aliases]
            for a in aliases:
                keys = self._alias_index.setdefault(normalize_label(a), [])
                if m.canonical_key not in keys:
                    keys.append(m.canonical_key)

    # -- individual tiers -------------------------------------------------

    def _priority_of(self, canonical_key: str) -> int:
        """The concept's declared ``match_priority``, or 0 when it declares none.

        0 rather than a mid-scale guess: a v1 rulebook declares no priority anywhere, so every
        concept ties and every ordering below degenerates to exactly the order it had before.
        """
        m = self._by_key.get(canonical_key)
        return m.match_priority if (m is not None and m.match_priority is not None) else 0

    def _by_priority(self, keys: list[str]) -> list[str]:
        """Highest ``match_priority`` first, ties left in the order given (the sort is stable)."""
        return sorted(keys, key=self._priority_of, reverse=True)

    def _exact(self, norm: str, allowed=None, reroute=None) -> Candidate | None:
        """An exact alias hit, preferring one the caller's scoping allows.

        ``allowed`` is a predicate over canonical keys (the statement/section/exclusion gate).
        When several concepts share the alias, the highest-``match_priority`` claimant that fits
        where the caption was printed wins. The rulebook's binding order runs the alias tier in
        descending priority and says in as many words never to pick by declaration order, which is
        what taking the first claimant was: 83 aliases in the shipped file are claimed by more than
        one concept, so for those the answer was decided by where an editor happened to add a row.

        ``reroute`` is consulted ONLY when every claimant was refused — a caption that is an alias
        of one leaf of a collision family, printed under the banner of another, is answered by the
        banner instead of being left unmapped.
        """
        keys = self._alias_index.get(norm) or []
        if not keys:
            return None
        if allowed is None:
            return Candidate(max(keys, key=self._priority_of), MappingMethod.EXACT, 1.0)
        ok = [k for k in keys if allowed(k)]
        if ok:
            return Candidate(max(ok, key=self._priority_of), MappingMethod.EXACT, 1.0)
        for k in keys:
            target = reroute(k) if reroute is not None else None
            if target:
                return Candidate(target, MappingMethod.EXACT, 1.0, rerouted_from=k)
        return None

    def _vetoed(self, canonical_key: str, caption: str) -> bool:
        """Whether the concept's ``exclude_hints`` rule this caption out.

        The field is named exclude and the ontology editor presents it as "never map a caption
        like this here", so it has to hold across every tier. Applying it only inside the rule
        tier meant an excluded caption could still arrive via fuzzy or an alias — an editor
        would add the exclusion, see nothing change, and have no way to fix a mis-mapping.
        """
        m = self._by_key.get(canonical_key)
        if m is None or not m.exclude_hints:
            return False
        text = caption.lower()
        return any(re.search(ex, text) for ex in m.exclude_hints)

    def _rule(self, raw: str) -> Candidate | None:
        text = raw.lower()
        best: Candidate | None = None
        for m in self.ontology.mappings:
            # A locked residual is unreachable by matching, and a regex or keyword hint authored on
            # one would otherwise reopen the hole the alias index was closed for.
            if m.canonical_key in self._locked:
                continue
            if any(re.search(ex, text) for ex in m.exclude_hints):
                continue
            hit = False
            if any(re.search(rx, text) for rx in m.regex_hints):
                hit = True
            elif m.keyword_hints and all(kw.lower() in text for kw in m.keyword_hints):
                hit = True
            if hit:
                cand = Candidate(m.canonical_key, MappingMethod.RULE, 0.95)
                if best is None:
                    best = cand
                else:
                    # multiple rule hits → ambiguous, drop confidence
                    best = Candidate(best.canonical_key, MappingMethod.RULE, 0.6)
        return best

    @staticmethod
    def _alias_coverage(caption: str, alias: str) -> float:
        """Share of the ALIAS's words the caption accounts for, tolerating misspellings.

        Direction matters: a section heading ("LIABILITIES") is trivially contained in a
        longer alias ("non-current lease liabilities"), so measuring how much of the *caption*
        is explained rewards fragments. Measuring how much of the *alias* is explained is what
        separates a real match from a substring of one.

        Token matching is itself fuzzy, because exact identity would punish the typos this
        tier exists to absorb ("trade recievables" covers "receivables").
        """
        alias_tokens = alias.split()
        if not alias_tokens:
            return 0.0
        caption_tokens = caption.split()
        if not caption_tokens:
            return 0.0
        hit = 0
        for at in alias_tokens:
            if any(at == ct or fuzz.ratio(at, ct) >= 80 for ct in caption_tokens):
                hit += 1
        return hit / len(alias_tokens)

    def _fuzzy_score(self, norm: str, alias: str) -> float:
        """Length-aware similarity, weighted by how much of the alias is covered.

        Deliberately NOT ``token_set_ratio``: that scores 100 whenever the caption's tokens
        are a subset of the alias's, so every heading and wrapped-line fragment scored a
        perfect 1.0 against some longer concept and was auto-accepted with false certainty
        (observed on a real filing: "LIABILITIES" -> non-current lease liabilities at 1.00).
        ``token_sort_ratio`` keeps length differences visible, and the coverage factor pulls
        down matches that only explain a small part of the concept they claim to be.
        """
        base = fuzz.token_sort_ratio(norm, alias) / 100.0
        coverage = self._alias_coverage(norm, alias)
        return base * (0.4 + 0.6 * coverage)

    def _fuzzy(self, norm: str) -> list[Candidate]:
        """Best fuzzy candidate per concept. Scores are EVIDENCE: the decision policy in
        `match` only lets fuzzy decide alone when it is near-exact (see `_fuzzy_accepts`)."""
        out: list[Candidate] = []
        for key, aliases in self._alias_by_key.items():
            if not aliases:
                continue
            best = max((self._fuzzy_score(norm, a) for a in aliases), default=0.0)
            if best > 0:
                out.append(Candidate(key, MappingMethod.FUZZY, best))
        # Score first, so priority can never outrank evidence; priority only settles a genuine tie,
        # where the alternative was dict insertion order deciding which of two equally-scored
        # concepts survives the shortlist cap below.
        out.sort(key=lambda c: (c.score, self._priority_of(c.canonical_key)), reverse=True)
        return out

    def _fuzzy_accepts(self, norm_segments: list[str], cand: Candidate) -> bool:
        """Whether a fuzzy-only match is strong enough to stand on its own.

        Requires BOTH a high combined score and that the caption explains most of the
        alias — a string method may only decide when it is essentially an exact hit, since
        it measures spelling, not meaning. Anything weaker is left for a human or the LLM
        rather than asserted.
        """
        s = self.settings.extraction
        if cand.score < s.fuzzy_accept:
            return False
        aliases = self._alias_by_key.get(cand.canonical_key) or []
        best_cov = max((self._alias_coverage(n, a) for a in aliases for n in norm_segments),
                       default=0.0)
        return best_cov >= s.fuzzy_min_alias_coverage

    def _ensure_alias_embeddings(self) -> None:
        """Embed every alias once (lazily) and index it by canonical key. Cached for the life
        of the matcher so a batch of captions reuses the same alias vectors."""
        if self._alias_vecs is not None:
            return
        pairs = [(key, alias) for key, aliases in self._alias_by_key.items()
                 for alias in aliases if alias]
        if not pairs:
            self._alias_vecs = []
            return
        vectors = self.embedding_provider.embed([a for _k, a in pairs])
        indexed: list[tuple[str, list[float]]] = []
        for (key, _alias), vec in zip(pairs, vectors):
            if vec:
                indexed.append((key, list(vec)))
        self._alias_vecs = indexed

    def _embedding(self, raw: str) -> list[Candidate]:
        """Cosine similarity of the raw caption against alias embeddings — catches paraphrases
        with no shared tokens ("Cash & bank balances" ↔ "Cash and cash equivalents"). Returns
        the best-scoring candidate per canonical key. A provider that is absent, unimplemented,
        or errors just yields no evidence so the rest of the ensemble carries on."""
        if self.embedding_provider is None:
            return []
        try:
            self._ensure_alias_embeddings()
            if not self._alias_vecs:
                return []
            query = self.embedding_provider.embed([raw])
        except Exception:  # noqa: BLE001 — NotImplementedError / provider unreachable
            return []
        if not query or not query[0]:
            return []
        qv = list(query[0])
        best: dict[str, float] = {}
        for key, vec in self._alias_vecs:
            score = _cosine(qv, vec)
            if score > best.get(key, -1.0):
                best[key] = score
        out = [Candidate(k, MappingMethod.EMBEDDING, max(0.0, min(1.0, s)))
               for k, s in best.items()]
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def _build_system(self) -> str:
        """Base instruction + the ontology's global extraction policies + worked examples."""
        g = self.ontology.global_rules
        lines: list[str] = [_LLM_SYSTEM]
        policies: list[str] = []
        policies += list(g.parent_child_allocation)
        if g.duplicate_fact_rule:
            policies.append(g.duplicate_fact_rule)
        if g.other_income_rule:
            policies.append(g.other_income_rule)
        policies += list(g.others_policy)
        if g.totals_policy:
            policies.append(g.totals_policy)
        if g.no_fabricated_split:
            policies.append(g.no_fabricated_split)
        if policies:
            lines.append("\nPolicies to follow:")
            lines += [f"- {p}" for p in policies]
        if self.ontology.worked_examples:
            lines.append("\nWorked examples:")
            for ex in self.ontology.worked_examples[:6]:
                lines.append("- " + json.dumps(ex.model_dump(exclude_defaults=True), ensure_ascii=False))
        return "\n".join(lines)

    def _concept_payload(self, keys: list[str]) -> list[dict]:
        """Candidate concepts with the criteria the LLM reasons over — definition, include/
        exclude, confusable-with (as labels), value_scope. Non-extracted headings skipped."""
        out = []
        for k in keys:
            m = self._by_key.get(k)
            if m is None or m.extraction_mode == "do_not_extract":
                continue
            # Also the choke point for the residual lock, not only `_extractable_keys`: the capped
            # shortlist in `match` is assembled from fuzzy/embedding/rule keys rather than from that
            # list, so a bucket kept out of one route has to be kept out of the other as well. A
            # concept the model cannot see is a concept the model cannot pick.
            if k in self._locked:
                continue
            entry: dict = {
                "canonical_key": k,
                "label": m.label or k.replace("_", " "),
                "definition": m.meaning(),
                "value_scope": m.value_scope,
                "example_aliases": m.aliases_for(self.locale)[:4],
            }
            if m.include:
                entry["include"] = m.include
            if m.exclude:
                entry["exclude"] = m.exclude
            if m.confusable_with:
                entry["confusable_with"] = [
                    (self._by_key[c].label or c) for c in m.confusable_with if c in self._by_key
                ]
            if m.decomposition_rule:
                entry["decomposition_rule"] = m.decomposition_rule
            out.append(entry)
        return out

    def _extractable_keys(self) -> list[str]:
        """The concepts a caption may be MAPPED to.

        Locked residuals are excluded even though they are extracted: they are extracted by the
        section sweep, which reads the template and never comes through here. Leaving them in put
        every section's "Others" bucket in front of the model on every call.
        """
        return [k for k, m in self._by_key.items()
                if m.extraction_mode != "do_not_extract" and k not in self._locked]

    def _llm(self, raw: str, context: str | None, keys: list[str]) -> Candidate | None:
        """Description/criteria-based decision — the key driver in the ensemble."""
        if self.llm_provider is None:
            return None
        candidates = self._concept_payload(keys)
        if not candidates:
            return None
        user = json.dumps({"caption": raw, "context": context or "", "candidates": candidates},
                          ensure_ascii=False, indent=2)
        try:
            decision, meta = self.llm_provider.complete_structured(
                system=self._system,
                messages=[{"role": "user", "content": user}],
                response_schema=LlmMappingDecision,
                max_tokens=512,
            )
        except Exception as exc:  # noqa: BLE001
            # Provider unreachable/misconfigured (commonly a missing API key) → the
            # deterministic ensemble decides. Record WHY: a run that silently degrades and
            # still reports itself as LLM-mapped overstates the quality of its own output.
            self.usage["failures"] += 1
            if not self.usage["last_error"]:
                self.usage["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return None
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(meta.get("input_tokens") or 0)
        self.usage["output_tokens"] += int(meta.get("output_tokens") or 0)
        self.usage["model"] = meta.get("model", self.usage["model"])
        key = (decision.canonical_key or "").strip()
        if not key or key not in self._by_key:
            return None
        return Candidate(key, MappingMethod.LLM, max(0.0, min(1.0, decision.confidence)),
                         allocation_status=(decision.allocation_status or "").strip() or None)

    # -- orchestration ----------------------------------------------------

    # Canonical keys are namespaced by statement (bs_/pl_/cf_/eq_...), so the statement a
    # caption was printed on constrains which concepts may win.
    _STMT_PREFIX = {"balance_sheet": "bs", "profit_and_loss": "pl", "cash_flow": "cf",
                    "changes_in_equity": "eq"}

    def _in_statement(self, canonical_key: str, statement: str | None) -> bool:
        """False only when the key clearly belongs to a DIFFERENT statement than the caption.

        Unknown statements, and keys whose prefix isn't one of the known statement
        namespaces, are always allowed — the constraint suppresses confident cross-statement
        errors without silently dropping concepts it cannot place.
        """
        want = self._STMT_PREFIX.get(statement or "")
        if not want:
            return True
        prefix = canonical_key.split("_", 1)[0]
        if prefix not in set(self._STMT_PREFIX.values()):
            return True
        return prefix == want

    def _section_of(self, text: str | None) -> str | None:
        return section_of_banner(text)

    def _in_section(self, canonical_key: str, section: str | None) -> bool:
        """False only when the key belongs to a DIFFERENT section than the banner names.

        Keys that carry no section namespace (``bs_total_assets``, ``pl_profit_before_tax``)
        and unrecognised banners are always allowed: like the statement constraint, this
        suppresses a confident wrong answer without dropping concepts it cannot place.
        """
        want = section_of_banner(section)
        if not want:
            return True
        have = section_of_key(canonical_key)
        if have is None:
            # A key with no section namespace is normally unconstrained. The exception is one leaf
            # of a collision family: both P&L bottom lines are statement-level keys, so without this
            # arm "LOSS FOR THE YEAR" under a "TOTAL COMPREHENSIVE" banner is waved through onto
            # `pl_profit_for_the_year` — the largest figure on the statement filed as the wrong fact
            # at confidence 1.0, with the comprehensive-income line left empty. Only ever narrows:
            # the banner must identify exactly one leaf, and a different one.
            return family_leaf_named_by(canonical_key, section) is None
        return have == want

    def _family_route(self, canonical_key: str, statement: str | None,
                      section: str | None, caption: str) -> str | None:
        """The sibling to re-route a REFUSED answer to, or None to let the refusal stand.

        Called only where the gate has already said no, so an answer the gate accepts is never
        rewritten. The destination goes through the same gate: re-routing may correct which variant
        of a fact was chosen, never smuggle a concept past the statement, exclusion or
        exclusive-vocabulary arms — and never into a locked residual, which no match may reach.
        """
        target = family_leaf_named_by(canonical_key, section)
        if target is None or target not in self._by_key or target in self._locked:
            return None
        if not self._allowed(target, statement, section, caption):
            return None
        return target

    def _record_route(self, from_key: str, to_key: str) -> None:
        """Count a re-route and remember the route, following `batch_refused`/`batch_unknown_ids`.

        Distinct routes only, and capped: what an auditor needs is which concepts were corrected,
        not one entry per row of a three-hundred-row filing.
        """
        self.usage["family_resolved"] += 1
        routes = self.usage["family_routes"]
        route = f"{from_key}->{to_key}"
        if route not in routes and len(routes) < 20:
            routes.append(route)

    def _allowed(self, canonical_key: str, statement: str | None,
                 section: str | None, caption: str = "") -> bool:
        """Whether a concept may be considered for a caption printed here.

        Two of the four constraints are structural, not lexical: the statement the page is, and
        the section banner the row sits under. The third is the concept's own declared exclusions,
        and the fourth is the caption naming a mutually exclusive class the concept is not in.
        They are combined in one place so no call site can apply only part of the scoping.
        """
        return (self._in_statement(canonical_key, statement)
                and self._in_section(canonical_key, section)
                and not (caption and self._vetoed(canonical_key, caption))
                and not (caption and _names_a_different_class(canonical_key, caption)))

    @staticmethod
    def _best_per_key(cands: list[Candidate]) -> list[Candidate]:
        """Highest-scoring candidate per concept, best first (segments can both propose one)."""
        best: dict[str, Candidate] = {}
        for c in cands:
            cur = best.get(c.canonical_key)
            if cur is None or c.score > cur.score:
                best[c.canonical_key] = c
        return sorted(best.values(), key=lambda c: c.score, reverse=True)

    def match(self, raw_label: str, context: str | None = None,
              statement: str | None = None, section: str | None = None) -> MappingResult:
        """A COMBINATION of methods — no single one is authoritative:

        exact identity short-circuits (free); otherwise rule / fuzzy / embedding each
        contribute candidate evidence, the LLM makes the semantic, criteria-based call
        (the key driver), and cross-method agreement adjusts confidence and review routing.
        Falls back to the deterministic margin policy when no LLM is configured/abstains.

        ``statement`` is the statement the caption was printed on (``balance_sheet``,
        ``profit_and_loss``, ``cash_flow``, ``changes_in_equity``) when the page classifier
        determined it. Concepts belonging to a *different* statement are then excluded: a
        balance-sheet caption must not resolve to a cash-flow concept just because the words
        overlap ("Finance costs" appears on both), which is otherwise a whole class of
        confidently-wrong mapping.

        ``section`` is the section banner the row was printed under ("NON-CURRENT
        LIABILITIES", 流動負債). Statements print one caption under two banners — a property
        developer's "Interest-bearing bank and other borrowings" and "Senior notes and domestic
        bonds" each appear once as non-current and once as current — so without the banner the
        two rows are indistinguishable and collapse onto one concept.
        """
        segments = label_segments(raw_label)
        norm = normalize_label(raw_label)
        s = self.settings
        scores: dict[str, float] = {}

        # 1. Exact normalized-alias identity — unambiguous and free. Tried on the caption and,
        #    for a bilingual line, on each script's half (either alone can be an exact alias).
        for seg in segments:
            # The scoping gate is handed to the alias lookup rather than applied after it: when
            # two concepts claim the same alias, the one that fits where this caption was printed
            # has to be the one returned.
            exact = self._exact(
                normalize_label(seg),
                allowed=lambda k: self._allowed(k, statement, section, raw_label),
                # An alias of one family leaf printed under another's banner is corrected here too,
                # not only on the batch path: the alias is real evidence of WHAT the row is, and
                # dropping it would trade a confidently-wrong answer for an unmapped row rather than
                # for the right one. The per-line path is also all there is when no LLM is running.
                reroute=lambda k: self._family_route(k, statement, section, raw_label))
            if exact:
                if exact.rerouted_from:
                    self._record_route(exact.rerouted_from, exact.canonical_key)
                return MappingResult(exact.canonical_key, exact.method, 1.0, [exact], False,
                                     {"exact": 1.0}, allocation_status="direct_exclusive",
                                     rerouted_from=exact.rerouted_from)

        # 2. Deterministic evidence from every method (each contributes; none forced out).
        #    Fuzzy/rule run per script segment and keep the best score per concept, so
        #    "REVENUE 收益" scores as well as the monolingual "Revenue" would.
        rule = next((r for r in (self._rule(seg) for seg in segments) if r), None)
        fuzzy = self._best_per_key([c for seg in segments for c in self._fuzzy(normalize_label(seg))])
        emb = self._embedding(raw_label)
        # Drop candidates belonging to another statement BEFORE they can win or shortlist.
        if rule and not self._allowed(rule.canonical_key, statement, section, raw_label):
            rule = None
        fuzzy = [c for c in fuzzy if self._allowed(c.canonical_key, statement, section, raw_label)]
        emb = [c for c in (emb or []) if self._allowed(c.canonical_key, statement, section, raw_label)]
        by_method: dict[str, set[str]] = {}
        pool: list[Candidate] = []
        if rule:
            scores["rule"] = rule.score
            by_method["rule"] = {rule.canonical_key}
            pool.append(rule)
        if fuzzy:
            scores["fuzzy"] = fuzzy[0].score
            by_method["fuzzy"] = {c.canonical_key for c in fuzzy[:5]}
            pool.extend(fuzzy[:5])
        if emb:
            scores["embedding"] = emb[0].score
            by_method["embedding"] = {c.canonical_key for c in emb[:5]}
            pool.extend(emb[:5])
        best_by_key: dict[str, Candidate] = {}
        for c in pool:
            cur = best_by_key.get(c.canonical_key)
            if cur is None or c.score > cur.score:
                best_by_key[c.canonical_key] = c
        # Score first, then declared priority: priority is an ordering, not a score, so it may only
        # settle a tie between two concepts the evidence rates equally. Which of those the shortlist
        # cap kept, and which one `det_top` reported, was previously dict insertion order.
        ranked = sorted(best_by_key.values(),
                        key=lambda c: (c.score, self._priority_of(c.canonical_key)), reverse=True)
        det_top = ranked[0] if ranked else None

        # 3. LLM semantic decision — the key driver, shown the deterministic shortlist
        #    (or every concept for a small ontology) plus each concept's criteria.
        if self.llm_enabled:
            all_keys = [k for k in self._extractable_keys()
                        if self._allowed(k, statement, section, raw_label)]
            if len(all_keys) <= s.extraction.llm_candidate_cap:
                shortlist = all_keys
            else:
                shortlist = list(dict.fromkeys(
                    ([rule.canonical_key] if rule else [])
                    + [c.canonical_key for c in fuzzy[:8]] + [c.canonical_key for c in emb[:8]]
                ))[: s.extraction.llm_candidate_cap]
            # Offered in descending match_priority, so the long specific concept is read before the
            # short generic one it collides with on token overlap ("Total assets less current
            # liabilities", 86, ahead of "Total current liabilities", 82 — the pair the rulebook's
            # own note on match_priority calls out). Applied AFTER the cap on purpose: priority
            # decides what the model reads first, never which concepts it is allowed to see, so a
            # high-priority concept with no evidence behind it cannot evict an evidenced one.
            shortlist = self._by_priority(shortlist)
            llm = self._llm(raw_label, context, shortlist)
            if llm is not None:
                scores["llm"] = llm.score
                # Corroboration across methods — agreement raises confidence, a strong
                # lexical disagreement lowers it and flags review.
                agreement = [meth for meth, keys in by_method.items() if llm.canonical_key in keys]
                conf = llm.score
                if agreement:
                    conf = min(1.0, llm.score + 0.10 * (1.0 - llm.score))
                elif det_top is not None and det_top.score >= s.extraction.fuzzy_accept:  # noqa: E501 - same combined scale
                    conf = llm.score * 0.85
                needs_review = (
                    conf < s.extraction.auto_accept_confidence
                    or (not agreement and det_top is not None and det_top.score >= s.extraction.fuzzy_accept)
                )
                alloc = llm.allocation_status
                if alloc is None:
                    scope = self._by_key[llm.canonical_key].value_scope
                    alloc = "direct_exclusive" if scope == "exclusive_leaf" else None
                return MappingResult(
                    canonical_key=llm.canonical_key, method=MappingMethod.LLM, confidence=conf,
                    candidates=[llm] + ranked[:4], needs_review=needs_review, scores=scores,
                    allocation_status=alloc, agreement=["llm", *agreement],
                )

        # 4. Deterministic decision (no LLM configured, or the LLM abstained).
        #    Fuzzy is a LAST RESORT. A fuzzy score measures string overlap, not meaning, so
        #    letting it auto-map floods the review queue with shaky guesses. Decide from the
        #    "meaningful" methods first (exact already returned above; then rule, then
        #    embedding). Only if they produce nothing do we consult fuzzy — and even then
        #    only when the match is essentially an exact string hit (>= fuzzy_accept);
        #    anything weaker is left unmapped for a human rather than guessed.
        if rule and rule.score >= 0.9:
            return MappingResult(rule.canonical_key, rule.method, rule.score, [rule], False,
                                 {**scores, "rule": rule.score}, allocation_status="direct_exclusive")

        primary = [c for c in ranked if c.method in (MappingMethod.RULE, MappingMethod.EMBEDDING)]
        if primary:
            top = primary[0]
            runner = primary[1].score if len(primary) > 1 else 0.0
            accept = (top.score >= s.extraction.auto_accept_confidence
                      and (top.score - runner) >= s.extraction.mapping_margin)
            return MappingResult(
                canonical_key=top.canonical_key, method=top.method, confidence=top.score,
                candidates=primary[:5], needs_review=not accept, scores=scores,
                allocation_status="direct_exclusive" if accept else "unmapped_review",
            )

        # Last resort: fuzzy only, and only when it is essentially certain — a high combined
        # score AND most of the alias explained (see `_fuzzy_accepts`).
        norm_segments = [normalize_label(seg) for seg in segments]
        norm_segments = [n for n in norm_segments if n]
        fuzzy_top = fuzzy[0] if fuzzy else None
        if fuzzy_top and self._fuzzy_accepts(norm_segments, fuzzy_top):
            return MappingResult(
                canonical_key=fuzzy_top.canonical_key, method=MappingMethod.FUZZY,
                confidence=fuzzy_top.score, candidates=fuzzy[:5], needs_review=False,
                scores=scores, allocation_status="direct_exclusive")
        # Nothing confident — do NOT emit a low-confidence fuzzy guess; route to review unmapped.
        return MappingResult(None, MappingMethod.UNMATCHED, 0.0, ranked[:5], True, scores,
                             allocation_status="unmapped_review")

    def match_batch(self, items: list[tuple[str, str]],
                    statement: str | None = None,
                    sections: dict[str, str | None] | None = None) -> dict[str, MappingResult]:
        """Batch mapping: decide many captions in one grounded LLM call so cross-line judgements
        (containment, residual, 'Others') have context. The model references the provided item_ids
        and candidate keys — it never invents a value; values/provenance stay on the deterministic
        LineItems. Falls back to per-line matching for anything the batch call can't resolve, or
        entirely when no LLM is configured.

        The batch is ONE SOURCE PAGE, not one statement, because that is how the caller groups
        (``stages.map_ontology``). A statement printed across two pages is therefore decided in two
        calls and does not see itself whole — which matters most for exactly the judgements above,
        since a subtotal and the lines it is made of can straddle the break. The setting that
        selects this path is still named ``per_statement``; treat that as naming the intent, not
        the unit. Changing the unit is a measured behaviour change (fewer, much larger calls,
        against a fixed response-token cap) and belongs in its own change, not in this docstring.

        ``items`` is a list of (item_id, source_label). ``sections`` maps an item_id to the
        section banner that item was printed under; a batch spans a whole page and therefore
        several sections, so the banner is per item, not per batch.

        The banner is given to the MODEL as well as being enforced after it answers. It used to
        be enforcement only: the model decided blind to the banner and a cross-section answer was
        then discarded, dropping the row to the weaker per-line path. Withholding the one piece of
        context the answer is graded on is how a caption that only its banner can disambiguate
        ("Others", the two "Non-controlling interests" of a comprehensive-income statement) got
        decided wrong and then thrown away.

        A refused answer inside a declared collision family (``CONCEPT_FAMILIES``) is now RE-ROUTED
        rather than discarded, because the banner already says which sibling was meant. Every other
        refusal — wrong statement, the concept's own exclusions, a caption naming a mutually
        exclusive class — still stands and is still counted as ``batch_refused``."""
        sec = sections or {}
        if not self.llm_enabled or not items:
            return {iid: self.match(label, statement=statement, section=sec.get(iid))
                    for iid, label in items}

        # Only concepts from THIS statement are offered, so the batch cannot place a caption
        # in another statement (see `match`). Section scoping is ALSO applied per decision
        # below, since one batch covers rows from several sections.
        # Descending match_priority, for the reason the per-line shortlist is ordered that way: one
        # batch offers the whole statement, so the order the model reads the list in is the only
        # ranking it gets.
        candidates = self._concept_payload(self._by_priority(
            [k for k in self._extractable_keys() if self._in_statement(k, statement)]))
        # No candidate to choose from is not a question worth asking. `_llm` already guards this;
        # the batch path did not, so a statement the ontology covers no concepts for (changes in
        # equity against the shipped ontology) spent a real provider call on an empty candidate
        # list and then fell back per line anyway.
        if not candidates:
            return {iid: self.match(label, statement=statement, section=sec.get(iid))
                    for iid, label in items}
        caption_by_id = dict(items)
        # The section given to the model is the NORMALISED token, not the raw banner: the gate
        # downstream compares `section_of_key` against `section_of_banner`, so naming the raw text
        # would hand the model a vocabulary its answer is not judged in. A banner that normalises
        # to nothing — an umbrella ("EQUITY AND LIABILITIES"), a group heading ("Adjustments
        # for:"), anything unrecognised — is omitted rather than passed through, because the gate
        # lets those rows go anywhere and the prompt must not imply a constraint that is not real.
        def _sec_token(iid: str) -> str | None:
            return section_of_banner(sec.get(iid))

        user = json.dumps({
            "instruction": "Map each source_item to exactly one candidate canonical_key by "
                           "meaning, applying the policies. Reference item_id and canonical_key; "
                           "do not output values. source_items are in the order they are printed "
                           "in the document. When an item carries a `section`, the concept you "
                           "choose must belong to that section.",
            "source_items": [
                {"item_id": iid, "caption": label,
                 **({"section": tok} if (tok := _sec_token(iid)) else {})}
                for iid, label in items
            ],
            "candidates": candidates,
        }, ensure_ascii=False, indent=2)
        try:
            decision, meta = self.llm_provider.complete_structured(
                system=self._batch_system,
                messages=[{"role": "user", "content": user}],
                response_schema=LlmBatchDecision,
                max_tokens=4096,
            )
        except Exception as exc:  # noqa: BLE001
            # Record WHY, as `_llm` does. A truncated or refused batch used to fall back per line
            # in complete silence, so a run whose every batch failed still reported itself as
            # LLM-mapped with no error to point at.
            self.usage["failures"] += 1
            if not self.usage["last_error"]:
                self.usage["last_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return {iid: self.match(label, statement=statement, section=sec.get(iid))
                    for iid, label in items}
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(meta.get("input_tokens") or 0)
        self.usage["output_tokens"] += int(meta.get("output_tokens") or 0)
        self.usage["model"] = meta.get("model", self.usage["model"])

        acc = self.settings.extraction.auto_accept_confidence
        out: dict[str, MappingResult] = {}
        for d in decision.mappings:
            # An item_id we did not ask about is not a decision about anything. Unchecked, it
            # reached the caller and crashed the stage (`by_id[iid]` → KeyError, killing the whole
            # extraction), and an id that happened to be another group's real row silently applied
            # this statement's decision to that one. It also defeated the gate: the caption lookup
            # returned "" for an unknown id, and both caption-dependent arms of `_allowed` are
            # skipped when the caption is empty.
            if d.item_id not in caption_by_id:
                self.usage["batch_unknown_ids"] += 1
                continue
            key = (d.canonical_key or "").strip()
            if not key or key not in self._by_key:
                continue
            # A concept from a different section than the row's banner is refused here for the
            # same reason it is refused in `match`. The model is now TOLD the section, so this is
            # a backstop rather than the only line of defence — and it still carries the two arms
            # that have nothing to do with sections: the concept's own exclusion criteria, and a
            # caption naming a mutually exclusive class.
            caption = caption_by_id[d.item_id]
            banner = sec.get(d.item_id)
            rerouted_from: str | None = None
            if not self._allowed(key, statement, banner, caption):
                # Before discarding it: when the answer is right about WHAT KIND of thing the row is
                # and wrong only about which section variant, the banner names the sibling and the
                # answer is corrected rather than lost. Discarding drops the row to the per-line
                # path, which sees one caption with no neighbours and is exactly why the batch call
                # exists — and for a bottom line whose caption arrives as a wrapped fragment there
                # is nothing left for that path to work from.
                target = self._family_route(key, statement, banner, caption)
                if target is None:
                    self.usage["batch_refused"] += 1
                    continue
                self._record_route(key, target)
                rerouted_from, key = key, target
            conf = max(0.0, min(1.0, d.confidence))
            alloc = (d.allocation_status or "").strip() or (
                "direct_exclusive" if self._by_key[key].value_scope == "exclusive_leaf" else None)
            out[d.item_id] = MappingResult(
                canonical_key=key, method=MappingMethod.LLM, confidence=conf,
                candidates=[Candidate(key, MappingMethod.LLM, conf, rerouted_from=rerouted_from)],
                needs_review=conf < acc, scores={"llm": conf},
                allocation_status=alloc, agreement=["llm"], rerouted_from=rerouted_from,
            )
        # Per-line fallback for any items the batch omitted.
        for iid, label in items:
            if iid not in out:
                out[iid] = self.match(label, statement=statement, section=sec.get(iid))
        return out

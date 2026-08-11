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
                      "failures": 0, "last_error": ""}
        # System prompt = the base instruction + the ontology's own extraction policies and
        # worked examples, so the LLM follows one consistent, auditable rulebook.
        self._system = self._build_system()

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
        for m in ontology.mappings:
            self._by_key[m.canonical_key] = m
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

    def _exact(self, norm: str, allowed=None) -> Candidate | None:
        """An exact alias hit, preferring one the caller's scoping allows.

        ``allowed`` is a predicate over canonical keys (the statement/section/exclusion gate).
        When several concepts share the alias, the one that fits where the caption was printed
        wins; with no predicate the first claimant does, as before.
        """
        keys = self._alias_index.get(norm) or []
        if not keys:
            return None
        if allowed is not None:
            keys = [k for k in keys if allowed(k)] or []
        if not keys:
            return None
        return Candidate(keys[0], MappingMethod.EXACT, 1.0)

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
        out.sort(key=lambda c: c.score, reverse=True)
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
        return [k for k, m in self._by_key.items() if m.extraction_mode != "do_not_extract"]

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
            return True
        return have == want

    def _allowed(self, canonical_key: str, statement: str | None,
                 section: str | None, caption: str = "") -> bool:
        """Whether a concept may be considered for a caption printed here.

        Two of the three constraints are structural, not lexical: the statement the page is,
        and the section banner the row sits under. The third is the concept's own declared
        exclusions. They are combined in one place so no call site can apply only part of the
        scoping.
        """
        return (self._in_statement(canonical_key, statement)
                and self._in_section(canonical_key, section)
                and not (caption and self._vetoed(canonical_key, caption)))

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
                allowed=lambda k: self._allowed(k, statement, section, raw_label))
            if exact:
                return MappingResult(exact.canonical_key, exact.method, 1.0, [exact], False,
                                     {"exact": 1.0}, allocation_status="direct_exclusive")

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
        ranked = sorted(best_by_key.values(), key=lambda c: c.score, reverse=True)
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
        """Per-statement mapping: decide ALL captions in one grounded LLM call so
        cross-line judgements (containment, residual, 'Others') have full context. The
        model references the provided item_ids and candidate keys — it never invents a
        value; values/provenance stay on the deterministic LineItems. Falls back to
        per-line matching for anything the batch call can't resolve, or entirely when no
        LLM is configured.

        ``items`` is a list of (item_id, source_label). ``sections`` maps an item_id to the
        section banner that item was printed under; a batch spans a whole page and therefore
        several sections, so the banner is per item, not per batch."""
        sec = sections or {}
        if not self.llm_enabled or not items:
            return {iid: self.match(label, statement=statement, section=sec.get(iid))
                    for iid, label in items}

        # Only concepts from THIS statement are offered, so the batch cannot place a caption
        # in another statement (see `match`). Section scoping is applied per decision below,
        # since one batch covers rows from several sections.
        candidates = self._concept_payload(
            [k for k in self._extractable_keys() if self._in_statement(k, statement)])
        user = json.dumps({
            "instruction": "Map each source_item to exactly one candidate canonical_key by "
                           "meaning, applying the policies. Reference item_id and canonical_key; "
                           "do not output values.",
            "source_items": [{"item_id": iid, "caption": label} for iid, label in items],
            "candidates": candidates,
        }, ensure_ascii=False, indent=2)
        try:
            decision, meta = self.llm_provider.complete_structured(
                system=self._system,
                messages=[{"role": "user", "content": user}],
                response_schema=LlmBatchDecision,
                max_tokens=4096,
            )
        except Exception:
            return {iid: self.match(label, statement=statement, section=sec.get(iid))
                    for iid, label in items}
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(meta.get("input_tokens") or 0)
        self.usage["output_tokens"] += int(meta.get("output_tokens") or 0)
        self.usage["model"] = meta.get("model", self.usage["model"])

        acc = self.settings.extraction.auto_accept_confidence
        out: dict[str, MappingResult] = {}
        for d in decision.mappings:
            key = (d.canonical_key or "").strip()
            if not key or key not in self._by_key:
                continue
            # A concept from a different section than the row's banner is refused here for the
            # same reason it is refused in `match`.
            caption = next((lbl for iid, lbl in items if iid == d.item_id), "")
            if not self._allowed(key, statement, sec.get(d.item_id), caption):
                continue
            conf = max(0.0, min(1.0, d.confidence))
            alloc = (d.allocation_status or "").strip() or (
                "direct_exclusive" if self._by_key[key].value_scope == "exclusive_leaf" else None)
            out[d.item_id] = MappingResult(
                canonical_key=key, method=MappingMethod.LLM, confidence=conf,
                candidates=[Candidate(key, MappingMethod.LLM, conf)],
                needs_review=conf < acc, scores={"llm": conf},
                allocation_status=alloc, agreement=["llm"],
            )
        # Per-line fallback for any items the batch omitted.
        for iid, label in items:
            if iid not in out:
                out[iid] = self.match(label, statement=statement, section=sec.get(iid))
        return out

"""The multi-strategy mapping ensemble.

Mapping a printed source line to a canonical template key is a *tiered ensemble*,
ordered cheap→expensive, each configurable per canonical key in the ontology:

1. exact / normalized lexical  (description-based)
2. rule-based                  (regex / keyword hints, minus exclude hints)
3. similarity / fuzzy          (rapidfuzz, absorbs typos / word-order / OCR noise)
4. semantic embeddings         (cosine similarity; multilingual → cross-lingual)
5. semantic + contextual LLM   (residual only, constrained to top-k candidates)

Combination policy: run in order; early-exit on a confident exact/rule hit; otherwise
gather candidate scores and accept the best **only if it clears a configurable margin
over the runner-up** — a narrow margin routes the item to review rather than guessing.
The winning method and per-strategy scores are recorded for audit.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from app.config import Settings, get_settings
from app.core.models.enums import MappingMethod
from app.schemas.ontology import OntologyDefinition, OntologyMapping


def normalize_label(text: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace (locale-agnostic)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class Candidate:
    canonical_key: str
    method: MappingMethod
    score: float


@dataclass
class MappingResult:
    canonical_key: str | None
    method: MappingMethod
    confidence: float
    candidates: list[Candidate] = field(default_factory=list)
    needs_review: bool = False
    scores: dict[str, float] = field(default_factory=dict)  # per-strategy best score


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

        # Precompute normalized alias → key index for exact/fuzzy tiers.
        self._alias_index: dict[str, str] = {}
        self._alias_by_key: dict[str, list[str]] = {}
        for m in ontology.mappings:
            aliases = m.aliases_for(self.locale)
            self._alias_by_key[m.canonical_key] = [normalize_label(a) for a in aliases]
            for a in aliases:
                self._alias_index[normalize_label(a)] = m.canonical_key

    # -- individual tiers -------------------------------------------------

    def _exact(self, norm: str) -> Candidate | None:
        key = self._alias_index.get(norm)
        if key:
            return Candidate(key, MappingMethod.EXACT, 1.0)
        return None

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

    def _fuzzy(self, norm: str) -> list[Candidate]:
        out: list[Candidate] = []
        for key, aliases in self._alias_by_key.items():
            if not aliases:
                continue
            match = process.extractOne(norm, aliases, scorer=fuzz.token_set_ratio)
            if match:
                out.append(Candidate(key, MappingMethod.FUZZY, match[1] / 100.0))
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def _embedding(self, raw: str) -> list[Candidate]:
        if self.embedding_provider is None:
            return []
        # Real impl: cosine similarity of raw vs alias embeddings. Deferred to the
        # embedding adapter; returns [] when unavailable so the cascade continues.
        try:
            self.embedding_provider.embed([raw])
        except NotImplementedError:
            return []
        return []

    def _llm(self, raw: str, top_k: list[Candidate], context: str | None) -> Candidate | None:
        if self.llm_provider is None or not top_k:
            return None
        # Real impl: constrain the LLM to the top-k candidate keys + context and let
        # it pick one with a confidence. Deferred to the LLM adapter.
        return None

    # -- orchestration ----------------------------------------------------

    def match(self, raw_label: str, context: str | None = None) -> MappingResult:
        norm = normalize_label(raw_label)
        s = self.settings
        scores: dict[str, float] = {}

        exact = self._exact(norm)
        if exact:
            return MappingResult(exact.canonical_key, exact.method, 1.0,
                                 [exact], False, {"exact": 1.0})

        rule = self._rule(raw_label)
        if rule and rule.score >= 0.9:
            return MappingResult(rule.canonical_key, rule.method, rule.score,
                                 [rule], False, {"rule": rule.score})

        candidates: list[Candidate] = []
        if rule:
            candidates.append(rule)
            scores["rule"] = rule.score

        fuzzy = self._fuzzy(norm)
        if fuzzy:
            scores["fuzzy"] = fuzzy[0].score
            candidates.extend(fuzzy[:5])

        emb = self._embedding(raw_label)
        if emb:
            scores["embedding"] = emb[0].score
            candidates.extend(emb[:5])

        # Rank the pooled candidates; keep best per key.
        best_by_key: dict[str, Candidate] = {}
        for c in candidates:
            cur = best_by_key.get(c.canonical_key)
            if cur is None or c.score > cur.score:
                best_by_key[c.canonical_key] = c
        ranked = sorted(best_by_key.values(), key=lambda c: c.score, reverse=True)

        if not ranked:
            return MappingResult(None, MappingMethod.UNMATCHED, 0.0, [], True, scores)

        top = ranked[0]
        runner = ranked[1].score if len(ranked) > 1 else 0.0
        margin = top.score - runner

        # LLM disambiguation only for the ambiguous residual (narrow margin or low top).
        if (margin < s.extraction.mapping_margin or top.score < s.extraction.fuzzy_accept) and self.llm_provider:
            llm = self._llm(raw_label, ranked[:5], context)
            if llm is not None:
                return MappingResult(llm.canonical_key, llm.method, llm.score,
                                     ranked[:5], llm.score < 0.85,
                                     {**scores, "llm": llm.score})

        accept = top.score >= s.extraction.fuzzy_accept and margin >= s.extraction.mapping_margin
        needs_review = not accept
        return MappingResult(
            canonical_key=top.canonical_key,
            method=top.method,
            confidence=top.score,
            candidates=ranked[:5],
            needs_review=needs_review,
            scores=scores,
        )

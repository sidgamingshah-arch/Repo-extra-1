"""Ontology mapping — description-based, LLM-driven.

Mapping a printed source line to a canonical template concept is done by **meaning**,
not string similarity. When an LLM provider is configured (the default), the model is
the decision-maker: it is shown the source caption plus candidate concepts *with their
descriptions* and picks the one that means the same thing — so "Amounts due from
customers", "Receivables from clients" and "Trade debtors" all resolve to
``trade_receivables`` even though none matches an alias lexically.

The cheap lexical tiers still run, but only to (a) short-circuit an unambiguous exact
alias hit, and (b) pre-shortlist the candidate concepts shown to the LLM when the
ontology is large:

1. exact / normalized lexical  (free, unambiguous → early exit)
2. rule-based                  (regex / keyword hints, minus exclude hints)
3. similarity / fuzzy          (rapidfuzz — shortlist only)
4. semantic embeddings         (cosine similarity — shortlist only)
5. **LLM description match**   (the decision: choose by meaning, with confidence)

Without an LLM provider (``extraction.llm_mapping=false`` or provider ``stub``) it
falls back to the deterministic ensemble with a margin-over-runner-up accept policy.
The winning method, confidence and per-strategy scores are recorded for audit.
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


class LlmMappingDecision(BaseModel):
    """Structured output for a single description-based mapping decision."""

    canonical_key: str = Field(description="the chosen canonical key, or \"\" if none fits")
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(default="", description="brief justification grounded in meaning")


_LLM_SYSTEM = (
    "You map a single raw line-item caption from a financial statement to ONE canonical "
    "concept, by MEANING. You are given the caption (with any context) and a list of "
    "candidate concepts, each with a canonical_key and a plain-language description. "
    "Choose the candidate whose description best matches what the caption represents — "
    "rely on financial meaning, not string similarity or shared words. If no candidate "
    "genuinely fits, return an empty canonical_key. Return calibrated confidence in "
    "[0,1]: high only when the concept is unambiguous."
)


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
        # Description-based LLM mapping is the primary strategy when a provider is present
        # and not disabled in config.
        self.llm_enabled = bool(llm_provider) and self.settings.extraction.llm_mapping
        # Token/usage accounting for the audit log (read by the mapping stage).
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "model": ""}

        # Precompute normalized alias → key index for exact/fuzzy tiers, and a concept
        # index (key → mapping) for description lookups.
        self._alias_index: dict[str, str] = {}
        self._alias_by_key: dict[str, list[str]] = {}
        self._by_key: dict[str, OntologyMapping] = {}
        for m in ontology.mappings:
            self._by_key[m.canonical_key] = m
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

    def _concept_payload(self, keys: list[str]) -> list[dict]:
        """Candidate concepts (key + label + description + a few aliases) for the LLM."""
        out = []
        for k in keys:
            m = self._by_key.get(k)
            if m is None:
                continue
            out.append({
                "canonical_key": k,
                "label": m.label or k.replace("_", " "),
                "description": m.description or "(no description provided)",
                "example_aliases": m.aliases_for(self.locale)[:4],
            })
        return out

    def _shortlist_keys(self, norm: str, raw: str) -> list[str]:
        """Candidate keys to show the LLM. Small ontologies pass every concept (best for
        description-based matching); large ones pass the lexically/semantically nearest."""
        cap = self.settings.extraction.llm_candidate_cap
        all_keys = list(self._by_key.keys())
        if len(all_keys) <= cap:
            return all_keys
        keys: list[str] = []
        for c in self._fuzzy(norm):
            if c.canonical_key not in keys:
                keys.append(c.canonical_key)
        for c in self._embedding(raw):
            if c.canonical_key not in keys:
                keys.append(c.canonical_key)
        r = self._rule(raw)
        if r and r.canonical_key not in keys:
            keys.insert(0, r.canonical_key)
        return keys[:cap]

    def _llm(self, raw: str, context: str | None) -> Candidate | None:
        """Description-based decision: let the LLM choose the concept by meaning."""
        if self.llm_provider is None:
            return None
        candidates = self._concept_payload(self._shortlist_keys(normalize_label(raw), raw))
        if not candidates:
            return None
        user = json.dumps({"caption": raw, "context": context or "", "candidates": candidates},
                          ensure_ascii=False, indent=2)
        try:
            decision, meta = self.llm_provider.complete_structured(
                system=_LLM_SYSTEM,
                messages=[{"role": "user", "content": user}],
                response_schema=LlmMappingDecision,
                max_tokens=512,
            )
        except Exception:
            return None  # provider unreachable/misconfigured → fall back to deterministic
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(meta.get("input_tokens") or 0)
        self.usage["output_tokens"] += int(meta.get("output_tokens") or 0)
        self.usage["model"] = meta.get("model", self.usage["model"])
        key = (decision.canonical_key or "").strip()
        if not key or key not in self._by_key:
            return None
        return Candidate(key, MappingMethod.LLM, max(0.0, min(1.0, decision.confidence)))

    # -- orchestration ----------------------------------------------------

    def match(self, raw_label: str, context: str | None = None) -> MappingResult:
        norm = normalize_label(raw_label)
        s = self.settings
        scores: dict[str, float] = {}

        # 1. Exact normalized-alias identity is unambiguous and free — take it.
        exact = self._exact(norm)
        if exact:
            return MappingResult(exact.canonical_key, exact.method, 1.0,
                                 [exact], False, {"exact": 1.0})

        # 2. Description-based LLM mapping is the PRIMARY strategy: choose the concept by
        #    meaning. Only fall through to the deterministic ensemble if the LLM abstains
        #    (no confident concept) or is unavailable.
        if self.llm_enabled:
            llm = self._llm(raw_label, context)
            if llm is not None:
                return MappingResult(
                    canonical_key=llm.canonical_key, method=llm.method, confidence=llm.score,
                    candidates=[llm],
                    needs_review=llm.score < s.extraction.auto_accept_confidence,
                    scores={"llm": llm.score},
                )

        # 3. Deterministic fallback ensemble (also the path when no LLM is configured).
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

        # Auto-accept requires a strong match (fuzzy_accept), a clear margin over the
        # runner-up, and a combined confidence at/above auto_accept_confidence; anything
        # short of all three is routed to the review queue.
        accept = (top.score >= s.extraction.fuzzy_accept
                  and margin >= s.extraction.mapping_margin
                  and top.score >= s.extraction.auto_accept_confidence)
        needs_review = not accept
        return MappingResult(
            canonical_key=top.canonical_key,
            method=top.method,
            confidence=top.score,
            candidates=ranked[:5],
            needs_review=needs_review,
            scores=scores,
        )

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
        # System prompt = the base instruction + the ontology's own extraction policies and
        # worked examples, so the LLM follows one consistent, auditable rulebook.
        self._system = self._build_system()

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
        except Exception:
            return None  # provider unreachable/misconfigured → deterministic decides
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

    def match(self, raw_label: str, context: str | None = None) -> MappingResult:
        """A COMBINATION of methods — no single one is authoritative:

        exact identity short-circuits (free); otherwise rule / fuzzy / embedding each
        contribute candidate evidence, the LLM makes the semantic, criteria-based call
        (the key driver), and cross-method agreement adjusts confidence and review routing.
        Falls back to the deterministic margin policy when no LLM is configured/abstains.
        """
        norm = normalize_label(raw_label)
        s = self.settings
        scores: dict[str, float] = {}

        # 1. Exact normalized-alias identity — unambiguous and free.
        exact = self._exact(norm)
        if exact:
            return MappingResult(exact.canonical_key, exact.method, 1.0, [exact], False,
                                 {"exact": 1.0}, allocation_status="direct_exclusive")

        # 2. Deterministic evidence from every method (each contributes; none forced out).
        rule = self._rule(raw_label)
        fuzzy = self._fuzzy(norm)
        emb = self._embedding(raw_label)
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
            all_keys = self._extractable_keys()
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
                elif det_top is not None and det_top.score >= s.extraction.fuzzy_accept:
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
        if rule and rule.score >= 0.9:
            return MappingResult(rule.canonical_key, rule.method, rule.score, [rule], False,
                                 {**scores, "rule": rule.score}, allocation_status="direct_exclusive")
        if not ranked:
            return MappingResult(None, MappingMethod.UNMATCHED, 0.0, [], True, scores,
                                 allocation_status="unmapped_review")
        top = ranked[0]
        runner = ranked[1].score if len(ranked) > 1 else 0.0
        margin = top.score - runner
        accept = (top.score >= s.extraction.fuzzy_accept
                  and margin >= s.extraction.mapping_margin
                  and top.score >= s.extraction.auto_accept_confidence)
        return MappingResult(
            canonical_key=top.canonical_key, method=top.method, confidence=top.score,
            candidates=ranked[:5], needs_review=not accept, scores=scores,
            allocation_status="direct_exclusive" if accept else "unmapped_review",
        )

    def match_batch(self, items: list[tuple[str, str]]) -> dict[str, MappingResult]:
        """Per-statement mapping: decide ALL captions in one grounded LLM call so
        cross-line judgements (containment, residual, 'Others') have full context. The
        model references the provided item_ids and candidate keys — it never invents a
        value; values/provenance stay on the deterministic LineItems. Falls back to
        per-line matching for anything the batch call can't resolve, or entirely when no
        LLM is configured.

        ``items`` is a list of (item_id, source_label)."""
        if not self.llm_enabled or not items:
            return {iid: self.match(label) for iid, label in items}

        candidates = self._concept_payload(self._extractable_keys())
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
            return {iid: self.match(label) for iid, label in items}
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
                out[iid] = self.match(label)
        return out

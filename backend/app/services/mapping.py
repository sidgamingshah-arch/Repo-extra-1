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
                self._alias_index.setdefault(normalize_label(a), m.canonical_key)

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
              statement: str | None = None) -> MappingResult:
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
        """
        segments = label_segments(raw_label)
        norm = normalize_label(raw_label)
        s = self.settings
        scores: dict[str, float] = {}

        # 1. Exact normalized-alias identity — unambiguous and free. Tried on the caption and,
        #    for a bilingual line, on each script's half (either alone can be an exact alias).
        for seg in segments:
            exact = self._exact(normalize_label(seg))
            if exact and self._in_statement(exact.canonical_key, statement):
                return MappingResult(exact.canonical_key, exact.method, 1.0, [exact], False,
                                     {"exact": 1.0}, allocation_status="direct_exclusive")

        # 2. Deterministic evidence from every method (each contributes; none forced out).
        #    Fuzzy/rule run per script segment and keep the best score per concept, so
        #    "REVENUE 收益" scores as well as the monolingual "Revenue" would.
        rule = next((r for r in (self._rule(seg) for seg in segments) if r), None)
        fuzzy = self._best_per_key([c for seg in segments for c in self._fuzzy(normalize_label(seg))])
        emb = self._embedding(raw_label)
        # Drop candidates belonging to another statement BEFORE they can win or shortlist.
        if rule and not self._in_statement(rule.canonical_key, statement):
            rule = None
        fuzzy = [c for c in fuzzy if self._in_statement(c.canonical_key, statement)]
        emb = [c for c in (emb or []) if self._in_statement(c.canonical_key, statement)]
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
                        if self._in_statement(k, statement)]
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

        # Last resort: fuzzy only, and only when it is essentially certain.
        fuzzy_top = fuzzy[0] if fuzzy else None
        if fuzzy_top and fuzzy_top.score >= s.extraction.fuzzy_accept:
            return MappingResult(
                canonical_key=fuzzy_top.canonical_key, method=MappingMethod.FUZZY,
                confidence=fuzzy_top.score, candidates=fuzzy[:5], needs_review=False,
                scores=scores, allocation_status="direct_exclusive")
        # Nothing confident — do NOT emit a low-confidence fuzzy guess; route to review unmapped.
        return MappingResult(None, MappingMethod.UNMATCHED, 0.0, ranked[:5], True, scores,
                             allocation_status="unmapped_review")

    def match_batch(self, items: list[tuple[str, str]],
                    statement: str | None = None) -> dict[str, MappingResult]:
        """Per-statement mapping: decide ALL captions in one grounded LLM call so
        cross-line judgements (containment, residual, 'Others') have full context. The
        model references the provided item_ids and candidate keys — it never invents a
        value; values/provenance stay on the deterministic LineItems. Falls back to
        per-line matching for anything the batch call can't resolve, or entirely when no
        LLM is configured.

        ``items`` is a list of (item_id, source_label)."""
        if not self.llm_enabled or not items:
            return {iid: self.match(label, statement=statement) for iid, label in items}

        # Only concepts from THIS statement are offered, so the batch cannot place a caption
        # in another statement (see `match`).
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
            return {iid: self.match(label, statement=statement) for iid, label in items}
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
                out[iid] = self.match(label, statement=statement)
        return out

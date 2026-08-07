"""Description-based, LLM-driven ontology mapping (services.mapping)."""
from __future__ import annotations

import json

from app.config import get_settings
from app.core.models.enums import MappingMethod
from app.schemas.ontology import OntologyDefinition, OntologyMapping
from app.services.mapping import LlmMappingDecision, OntologyMatcher


def _ontology() -> OntologyDefinition:
    return OntologyDefinition(
        ontology_key="t", target_template_key="t",
        mappings=[
            OntologyMapping(
                canonical_key="trade_receivables", label="Trade receivables",
                description="amounts owed by customers for goods or services sold on credit",
                aliases=["Trade receivables"],
            ),
            OntologyMapping(
                canonical_key="cash_and_equivalents", label="Cash and cash equivalents",
                description="cash on hand and bank balances readily available",
                aliases=["Cash and cash equivalents"],
            ),
        ],
    )


class _FakeLlm:
    """Simulates a description-based decision: pick the concept whose description shares
    the most meaning (word overlap here) with the caption."""

    id = "fake"

    def complete_structured(self, *, system, messages, response_schema, temperature=0.0, max_tokens=2048):
        payload = json.loads(messages[0]["content"])
        caption_words = set(payload["caption"].lower().replace(",", " ").split())
        best_key, best_overlap = "", 0
        for c in payload["candidates"]:
            overlap = len(caption_words & set(c["description"].lower().split()))
            if overlap > best_overlap:
                best_key, best_overlap = c["canonical_key"], overlap
        decision = LlmMappingDecision(canonical_key=best_key, confidence=0.92 if best_key else 0.0)
        return decision, {"model": "fake-llm", "input_tokens": 120, "output_tokens": 9}


def test_description_based_beats_fuzzy():
    """A caption that shares no alias words still maps correctly via its meaning."""
    s = get_settings()
    caption = "Amounts due from customers"  # not lexically close to "Trade receivables"

    # Deterministic (no LLM): fuzzy can't confidently reach trade_receivables → review.
    det = OntologyMatcher(_ontology(), settings=s).match(caption)
    assert det.method is not MappingMethod.LLM
    assert det.needs_review or det.canonical_key != "trade_receivables"

    # Description-based (LLM primary): resolves by meaning.
    m = OntologyMatcher(_ontology(), settings=s, llm_provider=_FakeLlm())
    assert m.llm_enabled is True
    res = m.match(caption)
    assert res.method is MappingMethod.LLM
    assert res.canonical_key == "trade_receivables"
    assert res.confidence == 0.92
    assert m.usage["calls"] == 1 and m.usage["input_tokens"] == 120


def test_exact_alias_short_circuits_without_calling_llm():
    m = OntologyMatcher(_ontology(), settings=get_settings(), llm_provider=_FakeLlm())
    res = m.match("Trade receivables")  # exact normalized alias
    assert res.method is MappingMethod.EXACT
    assert m.usage["calls"] == 0  # no tokens spent on an identity match


def test_llm_abstains_falls_back_to_deterministic():
    """If the LLM returns no concept, mapping falls back to the deterministic ensemble."""
    class _Abstain(_FakeLlm):
        def complete_structured(self, **kw):
            return LlmMappingDecision(canonical_key="", confidence=0.0), {
                "model": "fake-llm", "input_tokens": 50, "output_tokens": 2}

    m = OntologyMatcher(_ontology(), settings=get_settings(), llm_provider=_Abstain())
    res = m.match("Cash and cash equivalents")  # exact alias → resolves even after abstain path
    # exact short-circuits first, so this is EXACT; use a fuzzy-ish caption to exercise fallback:
    res2 = m.match("Cash & cash equivalents")
    assert res.canonical_key == "cash_and_equivalents"
    assert res2.canonical_key == "cash_and_equivalents"  # fuzzy fallback still works

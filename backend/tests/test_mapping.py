from __future__ import annotations

from app.core.models.enums import MappingMethod
from app.schemas.ontology import OntologyDefinition, OntologyMapping
from app.services.mapping import OntologyMatcher, normalize_label


def _ontology() -> OntologyDefinition:
    return OntologyDefinition(
        ontology_key="test",
        target_template_key="t",
        mappings=[
            OntologyMapping(
                canonical_key="assets.current.cash",
                aliases=["Cash and cash equivalents", "Cash & bank balances"],
                keyword_hints=["cash"],
                exclude_hints=["restricted cash"],
            ),
            OntologyMapping(
                canonical_key="assets.current.receivables",
                aliases=["Trade receivables", "Trade and other receivables"],
            ),
        ],
    )


def test_normalize_label():
    assert normalize_label("Cash & Bank  Balances!") == "cash bank balances"


def test_exact_match_early_exits():
    m = OntologyMatcher(_ontology())
    r = m.match("Cash and cash equivalents")
    assert r.canonical_key == "assets.current.cash"
    assert r.method == MappingMethod.EXACT and r.confidence == 1.0


def test_fuzzy_match_absorbs_typo():
    m = OntologyMatcher(_ontology())
    r = m.match("Trade recievables")  # misspelled
    assert r.canonical_key == "assets.current.receivables"
    assert r.method in (MappingMethod.FUZZY, MappingMethod.RULE)


def test_unmatched_routes_to_review():
    m = OntologyMatcher(_ontology())
    r = m.match("Deferred tax liability (net)")
    assert r.canonical_key is None or r.needs_review

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


def test_exclude_hints_veto_a_concept_across_every_tier():
    """The field is named exclude and the ontology editor presents it as "never map a caption
    like this here", so it has to hold everywhere — not only in the rule tier. While it applied
    to rules alone, an excluded caption still arrived via fuzzy or an alias, and an analyst
    adding the exclusion to fix a mis-mapping would see nothing change.
    """
    from app.schemas.ontology import OntologyDefinition, OntologyMapping
    from app.services.mapping import OntologyMatcher

    onto = OntologyDefinition(
        ontology_key="t", target_template_key="t", locale="en",
        mappings=[
            OntologyMapping(
                canonical_key="cf_cash_flow_from_investing_activities__disposal_of_subsidiaries",
                label="Disposal of subsidiaries",
                aliases=["Disposal of subsidiaries"],
                # A P&L add-back shares the wording but is not a movement of cash.
                exclude_hints=[r"\b(gain|loss)s? on disposal\b"],
            ),
        ],
    )
    m = OntologyMatcher(onto, locale="en")

    # The caption the concept is for still maps.
    assert m.match("Disposal of subsidiaries").canonical_key.endswith("disposal_of_subsidiaries")
    # The excluded wording does not — via the alias/exact tier...
    assert m.match("Gain on disposal of subsidiaries").canonical_key is None
    # ...nor via fuzzy, which is where it used to slip through.
    assert m.match("Gain on disposal of subsidiaries, net").canonical_key is None

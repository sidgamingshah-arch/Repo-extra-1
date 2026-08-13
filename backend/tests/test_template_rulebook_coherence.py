"""Two invariants the balance-sheet revision broke while the whole suite stayed green.

Neither restates a schema rule. ``validate_ontology_against_template`` checks that every CONCEPT key
resolves; nothing checked whether a rulebook's several statements of one concept's SECTION agree, and
nothing checked whether two declarations assert the same arithmetic.

Note what is deliberately NOT asserted here: that a rulebook's section ids equal the template's node
ids. They need not — ``mapping.section_token_of_scope`` reads the section name off the END of a scope
id, so ``bs_s3_current_liabilities`` and ``bs_s5_current_liabilities`` are one section to the gate,
and the shipped cash-flow sections are spelled differently in the two files today. Asserting equality
would be inventing a rule the code does not have.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from app.schemas.loader import load_ontology, load_template, resolve_inherits
from app.services.structural_checks import ontology_identities, relations

_SAMPLES = pathlib.Path(__file__).resolve().parents[1] / "app" / "sample" / "templates"
_ONTOLOGIES = ("hkfrs_hk_china_ontology.json", "hkfrs_hk_china_v2_ontology.json")


@pytest.fixture(scope="module")
def template():
    return load_template(json.loads((_SAMPLES / "hkfrs_hk_china_template.json").read_text()))


@pytest.mark.parametrize("filename", _ONTOLOGIES)
def test_a_concept_is_scoped_to_one_section_by_every_field_that_names_one(filename):
    """A residual whose policy names a different section from the one it inherits sweeps nothing.

    THE DEFECT THIS CLOSES, measured: renaming the balance sheet's section ids and following the
    rename through ``section_defaults``, its ``section_scope`` and every concept's ``inherits`` still
    left two ``residual_policy.section_scope`` values on the old names. ``stages.residual`` UNIONS a
    residual's inherited scope with its policy's, and a residual scoped to two sections has no
    candidate set at all — prohibition 5, "never spans sections" — so both balance-sheet residuals
    stopped sweeping and every unclaimed current-liabilities row came back ``residual_ineligible``
    instead of reaching its section's Others. Nothing in the schema or the loader says a word about
    it: an ``inherits`` naming no section is refused on the WRITE path, and these were not
    ``inherits``. Sixteen residual tests failed with a section id in the message and none of them
    named the field that was wrong.
    """
    raw = resolve_inherits(json.loads((_SAMPLES / filename).read_text()))
    disagreements = []
    for m in raw.get("mappings") or []:
        inherited = {s for s in (m.get("section_scope") or []) if s}
        declared = ((m.get("residual_policy") or {}).get("section_scope")
                    if isinstance(m.get("residual_policy"), dict) else None)
        if declared and inherited and declared not in inherited:
            disagreements.append((m.get("canonical_key"), sorted(inherited), declared))
    assert disagreements == [], (
        f"{filename}: residual_policy.section_scope disagrees with the inherited section_scope, "
        f"which leaves the residual spanning two sections and sweeping neither: {disagreements}")


def _assertion(rel) -> tuple:
    """What a relation ASSERTS, independent of how it was spelled or what it is called.

    Two declarations of one fact differ in ``id`` and agree on everything here, which is why the id
    cannot be the identity: ``identity:bs_balances`` in the template and
    ``ontology_identity:bs_balance`` in the rulebook were the same equation under two names.
    """
    signs = rel.signs or tuple(1 if rel.op == "sum" or i == 0 else -1
                               for i in range(len(rel.components)))
    return (rel.target, tuple(sorted(zip(rel.components, signs))))


@pytest.mark.parametrize("filename", _ONTOLOGIES)
def test_no_two_identities_assert_the_same_arithmetic(template, filename):
    """One equation, one identity — or coverage counts it twice and one break raises two cards.

    THE DEFECT THIS CLOSES: the template declared the footing as ``bs_balances`` and the v2 rulebook
    declared the identical equation as ``bs_balance``. Both resolved, both evaluated, both entered
    the coverage denominator, so "N relations passed" quoted a denominator with a duplicate in it.

    IDENTITIES only, not rollups. A rulebook identity restating a template rollup is the shipped
    design — ten pairs do it across the three statements, and they are how a relation the template can
    only declare as a blocking rollup gets an authored severity and note. Widening this to rollups
    would be asserting a design decision nobody made.
    """
    raw = json.loads((_SAMPLES / filename).read_text())
    ont = load_ontology(raw, resolve=raw.get("schema_version") == 2)
    seen: dict[tuple, list[str]] = {}
    for rel in relations(template) + ontology_identities(template, ont):
        if rel.broken or not rel.components or rel.kind == "rollup":
            continue
        seen.setdefault(_assertion(rel), []).append(rel.id)
    duplicates = {k: v for k, v in seen.items() if len(v) > 1}
    assert duplicates == {}, f"{filename}: one equation declared twice: {duplicates}"

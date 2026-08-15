"""Editing the mapping CRITERIA and the netting rules, not just aliases.

Aliases only help when the printed wording resembles one. What actually lets a caption be
resolved by meaning is the concept's definition and its include / exclude / confusable-with
criteria — and what restates a reported figure is a netting rule. Both must therefore be
editable, and both must go through the same versioned publish + validation as an alias edit:
a run references the exact ontology version it used, so an in-place mutation would rewrite
the explanation of past runs.
"""
from __future__ import annotations

import pytest

API = "/api/v1"


@pytest.fixture()
def h(auth):
    return auth("admin")


def _ontology(client, headers) -> dict:
    """The latest version of the seeded ontology — edits publish new ones as tests run."""
    rows = client.get(f"{API}/ontologies", headers=headers).json()
    return max(rows, key=lambda o: o["version"])


def _concept(client, headers, ont_id: str, key: str) -> dict:
    definition = client.get(f"{API}/ontologies/{ont_id}", headers=headers).json()["definition"]
    return next(m for m in definition["mappings"] if m["canonical_key"] == key)


def test_criteria_edit_publishes_a_new_version(client, h):
    ont = _ontology(client, h)
    key = "pl_income__other_income"
    res = client.patch(f"{API}/ontologies/{ont['id']}/mappings", headers=h, json={
        "canonical_key": key,
        "definition": "Income that is not revenue from contracts with customers.",
        "include": ["Sundry income", "Rental income not part of revenue"],
        "exclude": ["Revenue from contracts with customers"],
    })
    assert res.status_code == 200, res.text
    assert res.json()["version"] == ont["version"] + 1

    edited = _concept(client, h, res.json()["id"], key)
    assert edited["definition"].startswith("Income that is not revenue")
    assert "Sundry income" in edited["include"]
    assert edited["exclude"] == ["Revenue from contracts with customers"]

    # The version that ran before the edit is untouched.
    before = _concept(client, h, ont["id"], key)
    assert before["definition"] != edited["definition"]


def test_lists_are_trimmed_and_deduped(client, h):
    ont = _ontology(client, h)
    res = client.patch(f"{API}/ontologies/{ont['id']}/mappings", headers=h, json={
        "canonical_key": "pl_income__other_income",
        "include": ["  Sundry  ", "Sundry", "", "   ", "Other bits"],
    })
    assert res.status_code == 200, res.text
    got = _concept(client, h, res.json()["id"], "pl_income__other_income")["include"]
    assert got == ["Sundry", "Other bits"]


def test_confusable_with_must_name_real_concepts(client, h):
    """A typo here silently weakens the disambiguation the field exists to provide."""
    ont = _ontology(client, h)
    bad = client.patch(f"{API}/ontologies/{ont['id']}/mappings", headers=h, json={
        "canonical_key": "pl_income__other_income",
        "confusable_with": ["pl_does_not_exist"],
    })
    assert bad.status_code == 422
    assert "unknown" in bad.text.lower()

    ok = client.patch(f"{API}/ontologies/{ont['id']}/mappings", headers=h, json={
        "canonical_key": "pl_income__other_income",
        "confusable_with": ["pl_income__revenue_from_operations"],
    })
    assert ok.status_code == 200, ok.text


def test_an_invalid_regex_hint_is_refused_now_not_at_extraction_time(client, h):
    ont = _ontology(client, h)
    res = client.patch(f"{API}/ontologies/{ont['id']}/mappings", headers=h, json={
        "canonical_key": "pl_income__other_income",
        "regex_hints": ["other (income"],          # unbalanced group
    })
    assert res.status_code == 422
    assert "regex" in res.text.lower()


def test_value_scope_is_validated(client, h):
    ont = _ontology(client, h)
    assert client.patch(f"{API}/ontologies/{ont['id']}/mappings", headers=h, json={
        "canonical_key": "pl_income__other_income", "value_scope": "nonsense",
    }).status_code == 422
    ok = client.patch(f"{API}/ontologies/{ont['id']}/mappings", headers=h, json={
        "canonical_key": "pl_income__other_income", "value_scope": "exclusive_leaf",
    })
    assert ok.status_code == 200, ok.text


def test_netting_rule_upsert_and_delete_are_versioned(client, h):
    ont = _ontology(client, h)
    res = client.patch(f"{API}/ontologies/{ont['id']}/netting-rules", headers=h, json={
        "id": "test_rule",
        "target_key": "pl_expenses__cost_of_goods_sold",
        "subtract_keys": ["pl_expenses__general_and_administrative_expenses"],
        "condition": "Only when cost of sales is stated inclusive of administrative expenses.",
        "label": "Cost of sales inclusive of admin",
    })
    assert res.status_code == 200, res.text
    v2 = res.json()
    assert v2["version"] == ont["version"] + 1

    definition = client.get(f"{API}/ontologies/{v2['id']}", headers=h).json()["definition"]
    rule = next(r for r in definition["netting_rules"] if r["id"] == "test_rule")
    assert rule["target_key"] == "pl_expenses__cost_of_goods_sold"

    gone = client.patch(f"{API}/ontologies/{v2['id']}/netting-rules", headers=h,
                        json={"id": "test_rule", "delete": True})
    assert gone.status_code == 200, gone.text
    definition = client.get(f"{API}/ontologies/{gone.json()['id']}", headers=h).json()["definition"]
    assert all(r["id"] != "test_rule" for r in definition.get("netting_rules") or [])


def test_a_netting_rule_cannot_reference_a_concept_that_does_not_exist(client, h):
    """A rule pointing at a missing line never fires — indistinguishable from one that
    legitimately did not apply, so it is refused at edit time."""
    ont = _ontology(client, h)
    res = client.patch(f"{API}/ontologies/{ont['id']}/netting-rules", headers=h, json={
        "id": "bad_rule", "target_key": "pl_not_a_real_key",
    })
    assert res.status_code == 422
    assert "unknown" in res.text.lower()


def test_a_netting_rule_needs_a_target(client, h):
    ont = _ontology(client, h)
    res = client.patch(f"{API}/ontologies/{ont['id']}/netting-rules", headers=h,
                       json={"id": "no_target", "condition": "something"})
    assert res.status_code == 422


def test_criteria_and_netting_edits_are_admin_only(client, anon_client, auth, h):
    ont = _ontology(client, h)
    for path, payload in (
        (f"{API}/ontologies/{ont['id']}/mappings",
         {"canonical_key": "pl_income__other_income", "definition": "x"}),
        (f"{API}/ontologies/{ont['id']}/netting-rules",
         {"id": "r", "target_key": "pl_income__other_income"}),
    ):
        assert anon_client.patch(path, json=payload).status_code in (401, 403)
        res = client.patch(path, headers=auth("analyst"), json=payload)
        assert res.status_code == 403, f"{path} -> {res.status_code}"

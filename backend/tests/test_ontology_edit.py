"""Inline ontology editing: read a stored definition, edit one concept's rules, and get a
NEW version back (never a silent in-place mutation, so past runs stay explainable)."""
from __future__ import annotations

API = "/api/v1"


def _seeded_ontology(client) -> dict:
    """The rulebook IN FORCE for the reference template, as the PRODUCT reports it.

    Read off the template detail rather than re-derived here. Pinning it to hkfrs_hk_china_v1 by
    name made these tests edit one rulebook and assert against the screen showing another, once v2
    was adopted. Re-deriving it from GET /ontologies was no better: my first attempt took the
    highest version among the non-superseded rows and so picked a five-times-republished skeleton
    DRAFT — 188 empty stubs, no aliases — while the product was using v2. A test that reimplements
    the rule it is testing against can disagree with the product and still pass.
    """
    tpl = next(x for x in client.get(f"{API}/templates").json()
               if x["template_key"] == "hkfrs_hk_china_v1")
    ont = client.get(f"{API}/templates/{tpl['id']}/detail?locale=en").json().get("ontology")
    assert ont, "the reference template should have a rulebook in force"
    return ont


def _definition(client, oid: str) -> dict:
    r = client.get(f"{API}/ontologies/{oid}")
    assert r.status_code == 200, r.text
    return r.json()["definition"]


def test_get_ontology_returns_full_definition(client):
    ont = _seeded_ontology(client)
    body = client.get(f"{API}/ontologies/{ont['id']}").json()
    assert body["ontology_key"] == ont["ontology_key"]
    assert body["target_template_key"] == "hkfrs_hk_china_v1"
    assert len(body["definition"]["mappings"]) > 100    # the real 142-concept rulebook


def test_get_unknown_ontology_is_404(client):
    assert client.get(f"{API}/ontologies/does-not-exist").status_code == 404


def test_edit_aliases_publishes_a_new_version_and_leaves_the_old_intact(client):
    ont = _seeded_ontology(client)
    key = "bs_non_current_assets__property_plant_and_equipment"
    before = _definition(client, ont["id"])
    before_m = next(m for m in before["mappings"] if m["canonical_key"] == key)
    original_en = list((before_m.get("aliases_i18n") or {}).get("en") or [])

    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings", json={
        "canonical_key": key, "locale": "en",
        "aliases": ["Property, Plant and Equipment", "PP&E", "Fixed assets"],
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["version"] > ont["version"]
    assert out["ontology_key"] == ont["ontology_key"]     # the edit stays on the rulebook edited

    # The NEW version carries the edit...
    after_m = next(m for m in _definition(client, out["id"])["mappings"]
                   if m["canonical_key"] == key)
    assert after_m["aliases_i18n"]["en"] == [
        "Property, Plant and Equipment", "PP&E", "Fixed assets"]
    # ...the base list mirrors the default locale...
    assert after_m["aliases"] == after_m["aliases_i18n"]["en"]
    # ...and the version we edited from is untouched (audit history preserved).
    still = next(m for m in _definition(client, ont["id"])["mappings"]
                 if m["canonical_key"] == key)
    assert (still.get("aliases_i18n") or {}).get("en") == original_en


def test_editing_one_locale_does_not_clobber_another(client):
    ont = _seeded_ontology(client)
    key = "bs_non_current_assets__land_of_use_rights"
    base = _definition(client, ont["id"])
    zh_before = list((next(m for m in base["mappings"] if m["canonical_key"] == key)
                      .get("aliases_i18n") or {}).get("zh") or [])
    assert zh_before, "fixture expects Chinese aliases on this concept"

    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings", json={
        "canonical_key": key, "locale": "en", "aliases": ["Leasehold land"],
    })
    assert r.status_code == 200, r.text
    m = next(mm for mm in _definition(client, r.json()["id"])["mappings"]
             if mm["canonical_key"] == key)
    assert m["aliases_i18n"]["en"] == ["Leasehold land"]
    assert m["aliases_i18n"]["zh"] == zh_before      # the Chinese set survived


def test_aliases_are_trimmed_and_deduped(client):
    ont = _seeded_ontology(client)
    key = "bs_non_current_assets__right_of_use_assets"
    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings", json={
        "canonical_key": key, "locale": "en",
        "aliases": ["  ROU assets  ", "ROU assets", "", "   ", "Right-of-use"],
    })
    assert r.status_code == 200, r.text
    m = next(mm for mm in _definition(client, r.json()["id"])["mappings"]
             if mm["canonical_key"] == key)
    assert m["aliases_i18n"]["en"] == ["ROU assets", "Right-of-use"]


def test_edit_sign_convention_round_trips_to_the_template_screen(client):
    """Saving a sign must be visible where it was edited — the detail endpoint reads the
    ontology's sign_rule, so an expense/contra choice comes back as expense_contra."""
    ont = _seeded_ontology(client)
    key = "pl_expenses__general_and_administrative_expenses"
    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings", json={
        "canonical_key": key, "sign_convention": "expense_contra",
    })
    assert r.status_code == 200, r.text
    m = next(mm for mm in _definition(client, r.json()["id"])["mappings"]
             if mm["canonical_key"] == key)
    assert m["sign_rule"]["convention"] == "natural_negative"

    # The Template & Ontology screen (which reads the LATEST ontology) reflects it.
    tpl = next(x for x in client.get(f"{API}/templates").json()
               if x["template_key"] == "hkfrs_hk_china_v1")
    detail = client.get(f"{API}/templates/{tpl['id']}/detail?locale=en").json()
    assert detail["node_config"][key]["sign"] == "expense_contra"
    # The screen reads the rulebook in force, which is the one the edit was applied to. Naming a
    # literal key here is what made this test edit one rulebook and assert against another.
    assert detail["ontology"]["ontology_key"] == ont["ontology_key"]


def test_unknown_concept_and_bad_sign_are_rejected(client):
    ont = _seeded_ontology(client)
    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings", json={
        "canonical_key": "not_a_real_key", "aliases": ["x"]})
    assert r.status_code == 404
    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings", json={
        "canonical_key": "bs_non_current_assets__property_plant_and_equipment",
        "sign_convention": "sideways"})
    assert r.status_code == 422


def test_detail_exposes_raw_per_locale_aliases_for_editing(client):
    """The editor must load the RAW per-locale list, not the merged display set — otherwise
    saving the Chinese aliases would absorb the English fallbacks shown beside them."""
    tpl = next(x for x in client.get(f"{API}/templates").json()
               if x["template_key"] == "hkfrs_hk_china_v1")
    detail = client.get(f"{API}/templates/{tpl['id']}/detail?locale=zh").json()
    cfg = detail["node_config"]["bs_non_current_assets__property_plant_and_equipment"]
    assert cfg["canonical_key"] == "bs_non_current_assets__property_plant_and_equipment"
    # Raw zh list contains only Chinese aliases; the merged display list also has English.
    # Asserted structurally, not against one rulebook's exact wording: the point is that the raw
    # per-locale list is Chinese-only while the merged display list also carries the English
    # fallbacks. Pinning the literal "Property, Plant and Equipment" tied this to v1's casing and
    # broke on adoption of v2, which spells the same alias "Property, plant and equipment".
    from app.services.han import has_han

    assert cfg["aliases_locale"]
    assert all(has_han(a) for a in cfg["aliases_locale"]), cfg["aliases_locale"]
    english = [a for a in cfg["aliases"] if not has_han(a)]
    assert english, cfg["aliases"]                       # merged list keeps the English fallbacks
    assert any(a not in cfg["aliases_locale"] for a in english)


def test_editing_the_ontology_requires_admin(anon_client, auth):
    rows = anon_client.get(f"{API}/ontologies").json()
    oid = next(r["id"] for r in rows if r["ontology_key"] == "hkfrs_hk_china_v1")
    key = "bs_non_current_assets__property_plant_and_equipment"
    url = f"{API}/ontologies/{oid}/mappings"

    # The refused calls never reach the database, so their payload can be anything.
    denied = {"canonical_key": key, "aliases": ["nope"]}
    assert anon_client.patch(url, json=denied).status_code == 401
    assert anon_client.patch(url, json=denied, headers=auth("analyst")).status_code == 403
    assert anon_client.patch(url, json=denied, headers=auth("reviewer")).status_code == 403

    # The ACCEPTED one does, and this test is about authorisation, not content: it published a
    # version whose PPE aliases were ["nope"], which any later test reading the latest ontology
    # then had to survive. Resending the concept's existing aliases proves admin is allowed
    # through while leaving what the next test reads exactly as it found it.
    definition = anon_client.get(f"{API}/ontologies/{oid}",
                                 headers=auth("admin")).json()["definition"]
    current = next(m for m in definition["mappings"] if m["canonical_key"] == key)
    unchanged = {"canonical_key": key, "aliases": current.get("aliases") or [],
                 "aliases_i18n": current.get("aliases_i18n") or {}}
    assert anon_client.patch(url, json=unchanged, headers=auth("admin")).status_code == 200

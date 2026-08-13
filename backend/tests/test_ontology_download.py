"""Downloading the ontology structure that is expected of you, and the v2 seed.

An author writing a rulebook by hand has two questions the API could not previously answer: what
shape does the gate want, and what does a correct file look like for MY template. Since
``unknown_keys`` began refusing undeclared keys on upload, guessing costs a 422 per attempt.

The load-bearing claim of the skeleton endpoint is not that it produces JSON — it is that the JSON
it produces POSTs straight back and publishes. A skeleton that 422s on the user's first action
with it is worse than no download, so that round trip is asserted here and enforced inside the
generator (:class:`SkeletonError`).
"""
from __future__ import annotations

import json

import pytest

from app.schemas.loader import load_template, resolve_inherits
from app.schemas.ontology import OntologyDefinition, OntologyMapping, SectionDefaults
from app.services.ontology_skeleton import CURRENT_SCHEMA_VERSION

API = "/api/v1"
SEEDED_TEMPLATE = "hkfrs_hk_china_v1"


def _template(client) -> dict:
    rows = client.get(f"{API}/templates").json()
    return next(r for r in rows if r["template_key"] == SEEDED_TEMPLATE)


def _skeleton(client) -> dict:
    tpl = _template(client)
    r = client.get(f"{API}/ontologies/skeleton?template_id={tpl['id']}")
    assert r.status_code == 200, r.text
    return json.loads(r.content)


# --- GET /ontologies/schema --------------------------------------------------------------------

def test_schema_is_generated_from_the_model_the_upload_gate_validates_with(client):
    body = client.get(f"{API}/ontologies/schema").json()
    assert body["schema_version"] == CURRENT_SCHEMA_VERSION == 2
    # Byte-identical to the model's own schema: that identity is the whole point, because a
    # transcribed copy would describe a contract the gate had since stopped enforcing.
    assert body["json_schema"] == OntologyDefinition.model_json_schema()
    assert set(body["json_schema"]["required"]) == {"ontology_key", "target_template_key"}


def test_the_authoring_routes_are_not_shadowed_by_the_ontology_id_route(client):
    """Declared after ``/{ontology_id}`` these would be read as record ids and answer 404
    "Ontology not found" — a routing mistake wearing the costume of a missing row."""
    tpl = _template(client)
    assert client.get(f"{API}/ontologies/schema").status_code == 200
    assert client.get(f"{API}/ontologies/skeleton?template_id={tpl['id']}").status_code == 200
    assert client.get(f"{API}/ontologies/not-a-real-id").status_code == 404


def test_field_help_indexes_every_field_of_the_three_authored_blocks(client):
    """Set equality with the models, not a sample: the index is generated precisely so a field
    added to the schema is documented the moment it exists, and this is what pins that."""
    help_by_path = {e["path"]: e for e in client.get(f"{API}/ontologies/schema").json()["field_help"]}
    for prefix, model in (("", OntologyDefinition),
                          ("mappings[].", OntologyMapping),
                          ("section_defaults.<section_id>.", SectionDefaults)):
        expected = {f"{prefix}{f.alias or n}" for n, f in model.model_fields.items()}
        assert expected <= set(help_by_path), sorted(expected - set(help_by_path))
        for name, field in model.model_fields.items():
            entry = help_by_path[f"{prefix}{field.alias or name}"]
            assert entry["required"] is field.is_required()
            assert entry["help"]

    assert help_by_path["ontology_key"]["required"] is True
    assert help_by_path["locale"]["required"] is False
    # A closed set is spelled out, so the one value that is not accepted is visible before upload.
    assert '"exclusive_residual"' in help_by_path["mappings[].value_scope"]["help"]
    assert "defaults to \"exclusive_leaf\"" in help_by_path["mappings[].value_scope"]["help"]
    # The section layer's own vocabulary, and the distinction the fold turns on.
    assert "null = nothing said" in help_by_path["section_defaults.<section_id>.face_only"]["help"]
    # A nested block is named by its keys rather than expanded, so the index stays flat.
    assert "ResidualPolicy{" in help_by_path["mappings[].residual_policy"]["help"]


def test_field_help_speaks_json_not_python(client):
    """The help is read while typing JSON. ``True`` / ``'x'`` are not values that file accepts,
    and quoting them the Python way is how an author earns a 422 from the very text meant to
    prevent one."""
    help_by_path = {e["path"]: e for e in client.get(f"{API}/ontologies/schema").json()["field_help"]}
    assert "defaults to false" in help_by_path["mappings[].is_gross_parent"]["help"]
    assert "defaults to \"en\"" in help_by_path["locale"]["help"]
    # Nowhere in the index is a value quoted the Python way. Prose may contain an apostrophe; a
    # default or an accepted value may not.
    for entry in help_by_path.values():
        assert "defaults to '" not in entry["help"], entry
        assert "one of '" not in entry["help"], entry
        assert "| '" not in entry["help"], entry


# --- GET /ontologies/skeleton -----------------------------------------------------------------

def test_skeleton_is_served_as_a_named_json_attachment(client):
    tpl = _template(client)
    r = client.get(f"{API}/ontologies/skeleton?template_id={tpl['id']}")
    assert r.status_code == 200, r.text
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f"{SEEDED_TEMPLATE}_v{tpl['version']}_ontology_skeleton.json" in disposition
    assert r.headers["content-type"].startswith("application/json")


def test_skeleton_posts_straight_back_and_publishes(client):
    """The round trip, unmodified. This is the requirement — the user's first action with the
    file is to upload it, and a skeleton that fails there has cost them more than it saved."""
    skeleton = _skeleton(client)
    r = client.post(f"{API}/ontologies", json={"definition": skeleton})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["target_template_key"] == SEEDED_TEMPLATE
    assert out["mappings"] == len(skeleton["mappings"])

    stored = client.get(f"{API}/ontologies/{out['id']}").json()["definition"]
    assert stored["schema_version"] == 2
    # Nothing was dropped on the way through: the gate reports undeclared keys, and pydantic
    # silently discards them, so an equal definition proves both.
    assert stored == skeleton


def test_skeleton_accounts_for_every_canonical_key_the_template_declares(client):
    tpl = client.get(f"{API}/templates/{_template(client)['id']}").json()
    template = load_template(tpl["definition"])
    skeleton = _skeleton(client)

    keys = [m["canonical_key"] for m in skeleton["mappings"]]
    assert len(keys) == len(set(keys))
    assert set(keys) == template.all_canonical_keys()
    assert skeleton["target_template_key"] == template.template_key
    assert skeleton["target_template_version"] == tpl["version"]


def test_every_concept_inherits_a_declared_section_and_is_placed_by_it(client):
    """The section layer is inert unless ``inherits`` resolves: an unknown name leaves the concept
    with no statement and no scope, so the section-first binding order can never place it."""
    skeleton = _skeleton(client)
    sections = skeleton["section_defaults"]
    assert sections
    assert all(m["inherits"] in sections for m in skeleton["mappings"])

    resolved = resolve_inherits(skeleton)          # raises UnknownInheritsError otherwise
    assert all(m["statement"] and m["section_scope"] for m in resolved["mappings"])

    # A section banner names itself; a statement-level total ("Net assets") sits beside the
    # sections rather than inside one, and gets a section of its own instead of being the only
    # concept the layer never reaches.
    by_key = {m["canonical_key"]: m for m in resolved["mappings"]}
    assert by_key["bs_current_assets__inventories"]["inherits"] == "bs_s2_current_assets"
    assert by_key["bs_current_assets__inventories"]["temporality"] == "instant"
    assert by_key["bs_net_assets"]["inherits"] == "balance_sheet_top_level"
    assert by_key["pl_gross_profit"]["temporality"] == "duration"
    assert by_key["pl_gross_profit"]["unit_of_account"] == "subtotal"      # role: total
    # The banner carries no figure, so the skeleton must not invite aliases onto it.
    assert by_key["bs_s2_current_assets"]["extraction_mode"] == "do_not_extract"
    assert by_key["bs_s2_current_assets"]["value_scope"] == "not_applicable"


def test_skeleton_carries_the_template_label_and_leaves_the_authoring_slots_empty(client):
    skeleton = _skeleton(client)
    m = next(x for x in skeleton["mappings"]
             if x["canonical_key"] == "bs_non_current_assets__property_plant_and_equipment")
    assert m["label"] == "Property, Plant and Equipment"
    assert m["aliases"] == []
    # One alias slot per locale the template labels in — the languages an author is expected to
    # answer in, visible now rather than discovered from a parity gap later.
    assert m["aliases_i18n"] == {"en": [], "zh": []}
    assert skeleton["supported_locales"] == ["en", "zh"]
    assert set(skeleton["number_format_by_locale"]) == {"en", "zh"}
    assert (m["definition"], m["include"], m["exclude"], m["regex_hints"]) == ("", [], [], [])


def test_skeleton_does_not_claim_the_live_rulebooks_key(client):
    """Uploading under a seeded key publishes the next version OF it, and the Template screen and
    the parity page both read the highest version — an unfinished skeleton would become the
    rulebook those pages describe."""
    skeleton = _skeleton(client)
    assert skeleton["ontology_key"] not in {"hkfrs_hk_china", "hkfrs_hk_china_v1"}

    def _top(key: str) -> int:
        return max(r["version"] for r in client.get(f"{API}/ontologies").json()
                   if r["ontology_key"] == key)

    before = _top("hkfrs_hk_china")
    assert client.post(f"{API}/ontologies", json={"definition": skeleton}).status_code == 201
    assert _top("hkfrs_hk_china") == before


def test_unknown_template_id_is_404(client):
    assert client.get(f"{API}/ontologies/skeleton?template_id=nope").status_code == 404


def test_a_skeleton_the_gate_would_refuse_is_never_served(client, monkeypatch):
    """The generator's own guard. A stub key typo'd here would be dropped by pydantic and go on
    being served forever, so generation fails loudly instead of shipping a file whose first
    upload 422s."""
    from app.services import ontology_skeleton

    real_stub = ontology_skeleton._stub
    monkeypatch.setattr(ontology_skeleton, "_stub",
                        lambda *a, **k: {**real_stub(*a, **k), "regex_hint": ["typo"]})
    template = load_template(
        client.get(f"{API}/templates/{_template(client)['id']}").json()["definition"])
    with pytest.raises(ontology_skeleton.SkeletonError, match="regex_hint"):
        ontology_skeleton.build_skeleton(template)

    tpl = _template(client)
    r = client.get(f"{API}/ontologies/skeleton?template_id={tpl['id']}")
    assert r.status_code == 500 and "regex_hint" in r.text


def test_both_authoring_endpoints_require_admin(anon_client, auth):
    tpl = next(t for t in anon_client.get(f"{API}/templates").json()
               if t["template_key"] == SEEDED_TEMPLATE)
    for url in (f"{API}/ontologies/schema",
                f"{API}/ontologies/skeleton?template_id={tpl['id']}"):
        assert anon_client.get(url).status_code == 401
        assert anon_client.get(url, headers=auth("analyst")).status_code == 403
        assert anon_client.get(url, headers=auth("reviewer")).status_code == 403
        assert anon_client.get(url, headers=auth("admin")).status_code == 200


# --- the v2 seed ------------------------------------------------------------------------------

def test_the_shipped_rulebook_is_seeded_whole_and_selectable(client):
    """One template, one rulebook, and the rulebook seeded with every block it carries.

    This used to assert two generations were seeded side by side. They are consolidated: a concept
    authored twice in two vocabularies was a defect twice over, so the thin generation is retired and
    what is checked now is that the one that ships arrives complete — the section layer, the concept
    count and the target template, all read back through the API rather than off disk.
    """
    rows = client.get(f"{API}/ontologies").json()
    by_key: dict[str, dict] = {}
    for r in rows:
        if r["ontology_key"] not in by_key or r["version"] > by_key[r["ontology_key"]]["version"]:
            by_key[r["ontology_key"]] = r
    assert "hkfrs_hk_china" in by_key
    shipped = by_key["hkfrs_hk_china"]
    assert shipped["target_template_key"] == SEEDED_TEMPLATE
    assert shipped["superseded"] is False       # nothing replaces it

    definition = client.get(f"{API}/ontologies/{shipped['id']}").json()["definition"]
    assert definition["schema_version"] == 2 and len(definition["section_defaults"]) == 19
    assert len(definition["mappings"]) == 186
    assert len(definition["validation"]["identities"]) == 19


def test_every_version_under_the_shipped_key_is_that_rulebook(client):
    """Seeding never publishes a DIFFERENT rulebook as a version of this key.

    A run records the ``OntologyVersion`` id it used, and every consumer that reads "the latest
    version for this key" — the Template screen, the language-parity page — must get the rulebook
    that key names. Publishing something else under it would hand those pages a rulebook nobody
    chose, while runs pinned to older ids went on being explained by it.
    """
    rows = [r for r in client.get(f"{API}/ontologies").json()
            if r["ontology_key"] == "hkfrs_hk_china"]
    assert rows
    for row in rows:
        definition = client.get(f"{API}/ontologies/{row['id']}").json()["definition"]
        assert definition["ontology_key"] == "hkfrs_hk_china"
        # Inline edits publish further versions of the same file, so every version carries its
        # section layer — a version without one would be a different rulebook under this name.
        assert definition["schema_version"] == 2
        assert definition["section_defaults"]
        assert all(m.get("inherits") for m in definition["mappings"])


def test_a_shipped_rulebook_that_cannot_load_fails_seeding_loudly(tmp_path, monkeypatch):
    """The seed path used to write whatever was on disk. A file that no longer validates would
    then sit in the database as a row the read path chokes on — a 500 on the ontology editor, or a
    run that reports SUCCEEDED with its structural checks silently gone. Startup is the cheaper
    place to fail, and it names the file."""
    from app.db.base import SessionLocal
    from app.db.models import OntologyVersion
    from app.sample import reference

    broken = tmp_path / "broken_ontology.json"
    broken.write_text(json.dumps({
        "ontology_key": "probe_broken", "target_template_key": SEEDED_TEMPLATE,
        "mappings": [{"canonical_key": "bs_net_assets", "never_sweeep": ["typo"]}],
    }))
    monkeypatch.setattr(reference, "_ONTOLOGY", broken)

    with SessionLocal() as session:
        with pytest.raises(reference.ReferenceSeedError) as exc:
            reference.ensure_reference_data(session)
    assert "broken_ontology.json" in str(exc.value)
    assert "mappings[0].never_sweeep" in str(exc.value)

    # Every file is checked before anything is written, so a bad one takes nothing with it.
    from sqlalchemy import select

    with SessionLocal() as session:
        assert session.execute(
            select(OntologyVersion).where(OntologyVersion.ontology_key == "probe_broken_v2")
        ).scalars().first() is None

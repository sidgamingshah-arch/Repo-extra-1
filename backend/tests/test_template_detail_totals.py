"""A calculated total is a real, selectable node on the Template & Ontology screen — and a rulebook
that cannot be validated is refused.

Two defects of the same family are pinned here: a surface that answers confidently about the wrong
thing, and a gate that degrades to silence instead of failing.

THE TREE WALK. ``get_template_detail`` used to treat every entry in a statement's ``sections[]`` as
a heading and look for line items only among that entry's ``children``. The shipped template
deliberately declares its calculated lines as CHILDLESS top-level sections — Gross Profit sits
between cost of sales and operating expenses because that is where the statement prints it — so each
of them came out as an inert heading row with no ``node_config`` entry, and the screen resolved the
click to whichever concept its fallback chain reached. An analyst could then edit Property, Plant and
Equipment's aliases under a heading reading "Gross profit". The walk now branches on ``role``, the
way ``services.export._emit_nodes`` does.

THE ONTOLOGY GATE. ``_publish_new_version`` validated an edit against the target template only ``if
tpl_row is not None``, so an ontology whose ``target_template_key`` matched no stored template
published unvalidated and became the rulebook in force while mapping onto keys no template declares.

Order is asserted against the shipped file rather than a transcribed list: a second spelling of the
template's own order is a second thing that has to keep agreeing with it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

API = "/api/v1"
SEEDED_TEMPLATE = "hkfrs_hk_china_v1"

_DIR = Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"
TEMPLATE = json.loads((_DIR / "hkfrs_hk_china_template.json").read_text())


def _statement(stype: str) -> dict:
    return next(s for s in TEMPLATE["statements"] if s["type"] == stype)


def _row_id(node: dict) -> str:
    """The tree id the endpoint gives this node: headings are addressed by section, lines by key."""
    return f"sec:{node['node_id']}" if node.get("role") == "header" else node["canonical_key"]


def _statement_level_lines() -> list[str]:
    """Every line the template prints at statement level — the childless non-heading sections.

    Mostly the calculated totals (Gross profit, Net assets, Closing cash), plus the odd extracted
    line the statement prints outside any section. Derived from the file so a line added to a future
    template is covered without editing a list here: the whole CLASS of node has to stay selectable,
    not just the seventeen shipped today.
    """
    return [sec["canonical_key"]
            for stmt in TEMPLATE["statements"]
            for sec in stmt.get("sections", [])
            if sec.get("role") != "header" and not sec.get("children")]


def _template_line_items() -> int:
    """Non-heading nodes in the shipped template — the count ``POST /templates`` reports."""
    from app.schemas.loader import load_template

    return len([n for n in load_template(TEMPLATE).all_nodes() if n.role.value != "header"])


def _detail(client, locale: str = "en") -> dict:
    tpl = next(r for r in client.get(f"{API}/templates").json()
               if r["template_key"] == SEEDED_TEMPLATE)
    r = client.get(f"{API}/templates/{tpl['id']}/detail?locale={locale}")
    assert r.status_code == 200, r.text
    return r.json()


def _statement_rows(tree: list[dict], stype: str) -> list[dict]:
    """The rows between this statement's own heading and the next one."""
    start = next(i for i, n in enumerate(tree) if n["id"] == f"stmt:{stype}")
    rest = tree[start + 1:]
    end = next((i for i, n in enumerate(rest) if str(n["id"]).startswith("stmt:")), len(rest))
    return rest[:end]


# --- a calculated total is a selectable line -------------------------------------------------

def test_gross_profit_is_a_selectable_line_not_a_heading(client):
    """The row the analyst clicks and the concept the editor opens must be the same thing."""
    detail = _detail(client)
    row = next((n for n in detail["tree"] if n["id"] == "pl_gross_profit"), None)
    assert row is not None, (
        "Gross profit reached the tree only as 'sec:pl_gross_profit' — a heading id no "
        "node_config key can match, which is what sent the click to another concept")
    assert not row.get("head"), "a calculated total carries a figure; it is a line, not a heading"
    cfg = detail["node_config"].get("pl_gross_profit")
    assert cfg is not None, "a selectable line must carry the rules the editor edits"
    assert cfg["canonical_key"] == "pl_gross_profit"
    assert cfg["label"] == "Gross profit"
    # A total printed at statement level has no section above it, so it breadcrumbs to the
    # statement rather than borrowing the heading of whichever section happens to precede it.
    assert cfg["breadcrumb"] == "Profit And Loss"
    assert cfg["aggregation"] == "Sum of children"


@pytest.mark.parametrize("key", _statement_level_lines())
def test_every_statement_level_line_is_editable(client, key):
    """Not just Gross Profit: the whole class, in all three statements."""
    detail = _detail(client)
    assert key in detail["node_config"], f"{key} is a line the screen cannot answer about"
    row = next((n for n in detail["tree"] if n["id"] == key), None)
    assert row is not None and not row.get("head")


def test_a_totals_label_localizes_like_any_other_line(client):
    """A total reaches `_loc` on the same path as a line — it must not fall back to English."""
    detail = _detail(client, locale="zh")
    zh = _statement("profit_and_loss")["sections"]
    expected = next(s for s in zh if s["canonical_key"] == "pl_gross_profit")["label_i18n"]["zh"]
    assert detail["node_config"]["pl_gross_profit"]["label"] == expected


# --- position: the user's item 4, held from the Template-screen side --------------------------

def test_the_pl_tree_is_in_the_templates_own_order(client):
    """Serving a total as a real node must not move it. The template's order IS the statement's
    order, and a calculated line printed mid-statement that renders at the end is a spread no
    analyst can read against the filing."""
    rows = _statement_rows(_detail(client)["tree"], "profit_and_loss")
    top = [n["id"] for n in rows if n["lvl"] == 1]
    assert top == [_row_id(s) for s in _statement("profit_and_loss")["sections"]]


def test_gross_profit_sits_between_cost_of_sales_and_operating_expenses(client):
    """The concrete placement, named, because "in file order" is only reassuring if you know what
    the file says: Gross profit follows the cost-of-sales block and precedes operating expenses."""
    ids = [n["id"] for n in _statement_rows(_detail(client)["tree"], "profit_and_loss")]
    assert (ids.index("sec:pl_s2a_cost_of_sales")
            < ids.index("pl_expenses__total_cost_of_sales")
            < ids.index("pl_gross_profit")
            < ids.index("sec:pl_s2_expenses")
            < ids.index("pl_expenses__taxes_and_surcharges"))


# --- genuine headings keep behaving exactly as they did --------------------------------------

def test_a_genuine_heading_is_still_a_heading_over_its_children(client):
    detail = _detail(client)
    tree = detail["tree"]
    at = next(i for i, n in enumerate(tree) if n["id"] == "sec:pl_s1_income")
    assert tree[at]["head"] is True and tree[at]["lvl"] == 1
    assert tree[at]["id"] not in detail["node_config"], (
        "a heading carries no figure and no ontology rules, so it must not be selectable")

    section = next(s for s in _statement("profit_and_loss")["sections"]
                   if s["node_id"] == "pl_s1_income")
    children = tree[at + 1:at + 1 + len(section["children"])]
    assert [c["id"] for c in children] == [c["canonical_key"] for c in section["children"]]
    assert all(c["lvl"] == 2 and not c.get("head") for c in children)
    assert all(c["id"] in detail["node_config"] for c in children)


def test_the_line_item_count_is_the_templates_real_one(client):
    """One quantity, one spelling: the screen's count and the count `POST /templates` reports on
    upload are the same number. They disagreed while the seventeen statement-level lines were
    counted as headings here (170) and as line items there (187)."""
    detail = _detail(client)
    expected = _template_line_items()
    assert detail["template"]["line_items"] == expected
    assert len(detail["node_config"]) == expected
    lines = [n for n in detail["tree"]
             if not n.get("head") and not str(n["id"]).startswith("stmt:")]
    assert len(lines) == expected


# --- an unvalidatable rulebook is refused ----------------------------------------------------

_PROBE_KEY = "orphan_probe_tpl"
_PROBE_ONT_KEY = "orphan_probe_ont"
_PROBE_TEMPLATE = {
    "template_key": _PROBE_KEY,
    "name": "Orphan probe",
    "statements": [{
        "type": "balance_sheet",
        "sections": [{"node_id": "cash", "canonical_key": "cash", "label": "Cash",
                      "role": "line"}],
    }],
}
_PROBE_ONTOLOGY = {
    "ontology_key": _PROBE_ONT_KEY,
    "target_template_key": _PROBE_KEY,
    "mappings": [{"canonical_key": "cash", "label": "Cash", "aliases": ["Cash"]}],
}


def _drop(model, key_column, key: str) -> None:
    from sqlalchemy import delete

    from app.db.base import SessionLocal

    with SessionLocal() as session:
        session.execute(delete(model).where(key_column == key))
        session.commit()


@pytest.fixture
def probe_pair(client):
    """A throwaway template and a rulebook published against it, removed again afterwards.

    The ``client`` fixture is session-scoped and so is its database: a probe left behind would sit
    in every later test's `/templates` and `/ontologies` listing.
    """
    from app.db.models import OntologyVersion, TemplateVersion

    r = client.post(f"{API}/templates", json={"definition": _PROBE_TEMPLATE})
    assert r.status_code == 201, r.text
    tpl = r.json()
    r = client.post(f"{API}/ontologies", json={"definition": _PROBE_ONTOLOGY})
    assert r.status_code == 201, r.text
    try:
        yield tpl, r.json()
    finally:
        _drop(OntologyVersion, OntologyVersion.ontology_key, _PROBE_ONT_KEY)
        _drop(TemplateVersion, TemplateVersion.template_key, _PROBE_KEY)


@pytest.fixture
def orphaned_ontology(probe_pair):
    """The same rulebook, with its target template GONE — a renamed key, or a deleted template.

    Orphaned by dropping the template row rather than by publishing against a key that never
    existed, because the create path has always refused that: the hole was on the edit path.
    """
    from app.db.models import TemplateVersion

    _drop(TemplateVersion, TemplateVersion.template_key, _PROBE_KEY)
    return probe_pair[1]["id"]


def test_an_edit_to_a_rulebook_with_no_target_template_is_refused(client, orphaned_ontology):
    """`if tpl_row is not None` skipped validation entirely when the target template was missing,
    so this edit published — and a rulebook nothing had checked became the one in force."""
    r = client.patch(f"{API}/ontologies/{orphaned_ontology}/mappings",
                     json={"canonical_key": "cash", "aliases": ["Cash at bank"]})
    assert r.status_code == 422, r.text
    assert _PROBE_KEY in json.dumps(r.json()), (
        "the refusal has to name the template it could not find, or the author cannot fix it")


def test_a_netting_edit_takes_the_same_gate(client, orphaned_ontology):
    """Both inline-edit endpoints publish through `_publish_new_version`, so neither can be the
    one path where validation is skipped."""
    r = client.patch(f"{API}/ontologies/{orphaned_ontology}/netting-rules",
                     json={"id": "probe", "target_key": "cash", "subtract_keys": []})
    assert r.status_code == 422, r.text
    assert _PROBE_KEY in json.dumps(r.json())


def test_a_new_rulebook_naming_no_stored_template_is_refused(client):
    body = {"definition": {"ontology_key": "no_such_target_ont",
                           "target_template_key": "template_that_was_never_published",
                           "mappings": []}}
    r = client.post(f"{API}/ontologies", json=body)
    assert r.status_code == 422, r.text
    assert "template_that_was_never_published" in json.dumps(r.json())


# --- and the record says WHICH template version it was checked against -----------------------

def test_a_published_rulebook_states_the_template_version_it_was_checked_against(probe_pair):
    """The check runs against whichever template version is newest at publish time, which is not
    necessarily the version a run pins. Saying so on the response is what lets a reader tell,
    rather than assume, what a rulebook was held to."""
    tpl, ont = probe_pair
    assert ont.get("validated_against_template") == {
        "id": tpl["id"], "template_key": tpl["template_key"], "version": tpl["version"]}


def test_an_inline_edit_states_it_the_same_way(client, probe_pair):
    """Create and edit report it with one spelling, so neither path is the one you have to guess
    about."""
    tpl, ont = probe_pair
    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings",
                     json={"canonical_key": "cash", "aliases": ["Cash at bank"]})
    assert r.status_code == 200, r.text
    against = r.json().get("validated_against_template")
    assert against == {"id": tpl["id"], "template_key": _PROBE_KEY, "version": tpl["version"]}
    assert against == ont["validated_against_template"]


def test_an_edit_to_the_shipped_rulebook_names_the_shipped_template(client):
    """Not only for a probe: the rulebook actually in force reports it too."""
    ont = _detail(client)["ontology"]
    assert ont, "the reference template should have a rulebook in force"
    r = client.patch(f"{API}/ontologies/{ont['id']}/mappings",
                     json={"canonical_key": "pl_gross_profit", "aliases": ["Gross profit"]})
    assert r.status_code == 200, r.text
    against = r.json().get("validated_against_template")
    assert against, "an edit that says nothing about what validated it cannot be audited"
    assert against["template_key"] == SEEDED_TEMPLATE
    assert against["version"] == max(r["version"] for r in client.get(f"{API}/templates").json()
                                     if r["template_key"] == SEEDED_TEMPLATE)
    assert against["id"]

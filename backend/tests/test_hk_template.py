"""The HK/China (HKFRS/IFRS) template + companion ontology ship valid and load via the
real schema loaders and API endpoints."""
from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"
TEMPLATE = json.loads((_DIR / "hkfrs_hk_china_template.json").read_text())
ONTOLOGY = json.loads((_DIR / "hkfrs_hk_china_ontology.json").read_text())


def _statement(stype: str) -> dict:
    return next(s for s in TEMPLATE["statements"] if s["type"] == stype)


def _count(nodes) -> int:
    return sum(1 + _count(n.get("children", [])) for n in nodes)


def test_template_validates_and_is_tailored():
    from app.schemas.loader import (
        load_ontology, load_template, validate_ontology_against_template, validate_template,
    )

    tpl = load_template(TEMPLATE)
    assert validate_template(tpl) == []
    assert TEMPLATE["template_key"] == "hkfrs_hk_china_v1"
    # Three statements present.
    types = {s["type"] for s in TEMPLATE["statements"]}
    assert {"balance_sheet", "profit_and_loss", "cash_flow"} <= types
    # Balance-sheet identity (Assets = Equity + Liabilities) is declared.
    bs = _statement("balance_sheet")
    assert bs.get("identities"), "balance sheet should declare a balancing identity"
    # Chinese labels are present (tailored to HK/China) on many nodes.
    zh_nodes = [n for n in tpl.all_nodes() if n.label_i18n.get("zh")]
    assert len(zh_nodes) > 50

    # Ontology cross-checks against the template and carries the rich mapping signals.
    ont = load_ontology(ONTOLOGY)
    assert validate_ontology_against_template(ont, tpl) == []
    assert all(m.meaning() for m in ont.mappings)                 # definition/description present
    assert all(m.include and m.exclude for m in ont.mappings)     # inclusion/exclusion criteria
    assert any(m.value_scope == "exclusive_leaf" for m in ont.mappings)
    # Global extraction policies + worked examples + metadata came across (learnings).
    assert ont.global_rules.parent_child_allocation and ont.global_rules.others_policy
    assert ont.global_rules.no_fabricated_split
    assert ont.worked_examples and ont.metadata and ont.metadata.framework == "HKFRS"
    # Repeated captions like "Others" resolve to distinct concepts via context.
    others = [m for m in ont.mappings if m.label == "Others"]
    assert len(others) >= 4 and len({m.canonical_key for m in others}) == len(others)


def test_cash_flow_is_expanded():
    cf = _statement("cash_flow")
    # Comfortably more than the caller's baseline cash-flow rows.
    assert _count(cf["sections"]) >= 45
    labels = {n["label"] for s in cf["sections"] for n in s.get("children", [])}
    for extra in ("Interest received", "Income tax paid", "Principal elements of lease payments",
                  "Proceeds from issue of shares"):
        assert extra in labels, extra


def test_template_and_ontology_upload_via_api(client):
    """End-to-end: the template then the ontology upload through the real endpoints."""
    r = client.post("/api/v1/templates", json={"definition": TEMPLATE})
    assert r.status_code == 201, r.text
    r2 = client.post("/api/v1/ontologies", json={"definition": ONTOLOGY})
    assert r2.status_code == 201, r2.text

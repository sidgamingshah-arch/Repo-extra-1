from __future__ import annotations

from app.schemas.languages import evaluate_parity
from app.schemas.loader import (
    load_ontology,
    load_template,
    validate_ontology_against_template,
    validate_template,
)

TEMPLATE = {
    "template_key": "ifrs_min",
    "name": "IFRS Minimal",
    "statements": [{
        "type": "balance_sheet",
        "sections": [{
            "node_id": "assets.current", "canonical_key": "assets.current",
            "label": "Current assets", "role": "subtotal",
            "label_i18n": {"en": "Current assets", "zh": "流动资产",
                           "ar": "الأصول المتداولة", "fr": "Actifs courants"},
            "children": [
                {"node_id": "assets.current.cash", "canonical_key": "assets.current.cash",
                 "label": "Cash", "role": "line",
                 "label_i18n": {"en": "Cash", "zh": "现金", "ar": "النقد", "fr": "Trésorerie"}},
            ],
            "rollup": {"op": "sum", "children": ["assets.current.cash"]},
        }],
        "identities": [],
    }],
}

ONTOLOGY = {
    "ontology_key": "ifrs_min_multi",
    "target_template_key": "ifrs_min",
    "supported_locales": ["en", "zh", "ar", "fr"],
    "number_format_by_locale": {
        "en": {"decimal": ".", "thousands": ","},
        "fr": {"decimal": ",", "thousands": " "},
        "zh": {"decimal": ".", "thousands": ","},
        "ar": {"decimal": ".", "thousands": ","},
    },
    "mappings": [{
        "canonical_key": "assets.current.cash",
        "aliases": ["Cash"],
        "aliases_i18n": {"en": ["Cash"], "zh": ["现金"], "ar": ["النقد"], "fr": ["Trésorerie"]},
    }],
}


def test_template_loads_and_validates():
    tpl = load_template(TEMPLATE)
    assert validate_template(tpl) == []
    assert "assets.current.cash" in tpl.all_canonical_keys()


def test_template_rejects_bad_rollup():
    bad = {**TEMPLATE}
    import copy
    bad = copy.deepcopy(TEMPLATE)
    bad["statements"][0]["sections"][0]["rollup"]["children"] = ["does.not.exist"]
    tpl = load_template(bad)
    errors = validate_template(tpl)
    assert any("unknown node_id" in e.message for e in errors)


def test_ontology_validates_against_template():
    tpl = load_template(TEMPLATE)
    ont = load_ontology(ONTOLOGY)
    assert validate_ontology_against_template(ont, tpl) == []


def test_ontology_rejects_unknown_key():
    tpl = load_template(TEMPLATE)
    bad = {**ONTOLOGY, "mappings": [{"canonical_key": "not.in.template", "aliases": ["X"]}]}
    ont = load_ontology(bad)
    errors = validate_ontology_against_template(ont, tpl)
    assert any("does not exist" in e.message for e in errors)


def test_language_parity_full_for_seed_set():
    tpl = load_template(TEMPLATE)
    ont = load_ontology(ONTOLOGY)
    parity = {p.locale: p for p in evaluate_parity(tpl, ont)}
    assert set(parity) == {"en", "zh", "ar", "fr"}
    # With per-locale labels, aliases, number formats, OCR packs, and UI bundles,
    # all four seed languages are fully supported (input = output parity).
    for loc in ("en", "zh", "ar", "fr"):
        assert parity[loc].supported, f"{loc} missing: {parity[loc].missing}"
    assert parity["ar"].rtl is True

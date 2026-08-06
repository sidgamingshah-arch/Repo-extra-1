"""Supported-language registry — enforces input = output multilingual parity.

A language counts as ``supported`` only when ALL five parity artifacts exist:
OCR pack, locale number-format rules, ontology aliases for the active template,
template ``label_i18n``, and a UI translation bundle. The API exposes the supported
set and the UI offers only those languages — so the input set and output set are, by
construction, identical.

The seed set is English, Chinese, Arabic (RTL), and French.
"""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.ontology import OntologyDefinition
from app.schemas.template import TemplateDefinition


class LanguageParity(BaseModel):
    locale: str
    name: str
    rtl: bool = False
    has_ocr_pack: bool = False
    has_number_format: bool = False
    has_ontology_aliases: bool = False
    has_template_labels: bool = False
    has_ui_bundle: bool = False

    @property
    def supported(self) -> bool:
        return all([
            self.has_ocr_pack,
            self.has_number_format,
            self.has_ontology_aliases,
            self.has_template_labels,
            self.has_ui_bundle,
        ])

    @property
    def missing(self) -> list[str]:
        checks = {
            "ocr_pack": self.has_ocr_pack,
            "number_format": self.has_number_format,
            "ontology_aliases": self.has_ontology_aliases,
            "template_labels": self.has_template_labels,
            "ui_bundle": self.has_ui_bundle,
        }
        return [name for name, ok in checks.items() if not ok]


# Seed set confirmed with the user. ``rtl`` and OCR-pack availability are static
# facts about the language/engine; the other three flags are computed per
# template+ontology by ``evaluate_parity`` below.
SEED_LANGUAGES: dict[str, dict] = {
    "en": {"name": "English", "rtl": False, "has_ocr_pack": True},
    "zh": {"name": "Chinese", "rtl": False, "has_ocr_pack": True},
    "ar": {"name": "Arabic", "rtl": True, "has_ocr_pack": True},
    "fr": {"name": "French", "rtl": False, "has_ocr_pack": True},
}

# UI bundles present in the frontend. Backend tracks the fact for the parity gate.
UI_BUNDLES: set[str] = {"en", "zh", "ar", "fr"}


def evaluate_parity(
    template: TemplateDefinition | None,
    ontology: OntologyDefinition | None,
    locales: list[str] | None = None,
) -> list[LanguageParity]:
    """Compute parity for each seed (or requested) locale against the given
    template + ontology. With no template/ontology, only the static facts are known.
    """
    locales = locales or list(SEED_LANGUAGES)
    result: list[LanguageParity] = []
    for loc in locales:
        seed = SEED_LANGUAGES.get(loc, {"name": loc, "rtl": False, "has_ocr_pack": False})

        has_number_format = bool(ontology and loc in ontology.number_format_by_locale)
        has_ontology_aliases = bool(
            ontology and any(loc in m.aliases_i18n or loc == "en" for m in ontology.mappings)
        )
        has_template_labels = bool(
            template and all(loc in n.label_i18n or loc == "en"
                             for n in template.all_nodes())
        )
        result.append(LanguageParity(
            locale=loc,
            name=seed["name"],
            rtl=seed["rtl"],
            has_ocr_pack=seed["has_ocr_pack"],
            has_number_format=has_number_format,
            has_ontology_aliases=has_ontology_aliases,
            has_template_labels=has_template_labels,
            has_ui_bundle=loc in UI_BUNDLES,
        ))
    return result

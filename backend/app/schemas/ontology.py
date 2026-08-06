"""Ontology schema — rules that describe how to recognise each canonical line item
from arbitrary source descriptions, fix signs, find note refs, and decompose notes.

The ontology is *data, not code*: editable from the frontend, versioned, and
hot-swappable per job. Aliases/keyword/regex hints are **locale-scoped**
(``*_i18n``) so the same ontology drives extraction across the supported languages,
and ``number_format_by_locale`` makes number parsing locale-correct (a wrong
decimal/thousands separator silently corrupts values).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.models.enums import SignConvention


class NumberFormat(BaseModel):
    decimal: str = "."
    thousands: str = ","
    # negative markers understood by the parser
    negative: list[str] = Field(default_factory=lambda: ["paren", "minus"])
    # e.g. Indian grouping "1,23,456" vs western "123,456"
    grouping: Literal["western", "indian"] = "western"


class SignRule(BaseModel):
    convention: SignConvention = SignConvention.NATURAL
    flip_if_label_matches: list[str] = Field(default_factory=list)  # regexes


class NoteRefHint(BaseModel):
    expects_note: bool = False
    column_position: str = "after_label"
    regex: str = r"\bnote[s]?\.?\s*(\d+(?:\.\d+)?)"


class OntologyMapping(BaseModel):
    canonical_key: str
    aliases: list[str] = Field(default_factory=list)          # default-locale aliases
    aliases_i18n: dict[str, list[str]] = Field(default_factory=dict)  # per-locale
    keyword_hints: list[str] = Field(default_factory=list)
    regex_hints: list[str] = Field(default_factory=list)
    exclude_hints: list[str] = Field(default_factory=list)
    sign_rule: SignRule = Field(default_factory=SignRule)
    note_ref_hint: NoteRefHint = Field(default_factory=NoteRefHint)
    min_confidence_to_auto_accept: float = 0.85

    def aliases_for(self, locale: str | None) -> list[str]:
        out = list(self.aliases)
        if locale and locale in self.aliases_i18n:
            out = out + self.aliases_i18n[locale]
        # also include the English set as a cross-lingual fallback anchor
        if "en" in self.aliases_i18n:
            out = out + self.aliases_i18n["en"]
        return list(dict.fromkeys(out))  # dedupe, keep order


class DecompositionRule(BaseModel):
    """Defines the face↔note tie and the residual-as-'other' reconciliation (§20)."""

    id: str
    face_key: str
    note_match: dict = Field(default_factory=lambda: {"by": "note_number"})
    expected_children: list[str] = Field(default_factory=list)
    reconcile_op: Literal["sum_equals_face"] = "sum_equals_face"
    residual_allowed_as: str | None = "other"
    tolerance_abs: float = 1.0
    tolerance_rel: float = 0.001


class GlobalRules(BaseModel):
    credit_balance_lines: list[str] = Field(default_factory=list)  # key globs
    paren_means_negative: bool = True


class OntologyDefinition(BaseModel):
    schema_version: int = 1
    ontology_key: str
    target_template_key: str
    target_template_version: int | None = None
    locale: str = "en"
    supported_locales: list[str] = Field(default_factory=lambda: ["en"])
    number_format_by_locale: dict[str, NumberFormat] = Field(
        default_factory=lambda: {"en": NumberFormat()}
    )
    mappings: list[OntologyMapping] = Field(default_factory=list)
    decomposition_rules: list[DecompositionRule] = Field(default_factory=list)
    global_rules: GlobalRules = Field(default_factory=GlobalRules)

    def number_format(self, locale: str | None) -> NumberFormat:
        if locale and locale in self.number_format_by_locale:
            return self.number_format_by_locale[locale]
        return self.number_format_by_locale.get("en", NumberFormat())

    def canonical_keys(self) -> set[str]:
        return {m.canonical_key for m in self.mappings}

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


ValueScope = Literal[
    "exclusive_leaf",       # a stand-alone leaf value, no overlap with others
    "exclusive_child",      # a component of a gross parent (subtract from parent)
    "exclusive_residual",   # parent minus confirmed children (a computed residual)
    "not_applicable",       # headings / non-extracted rows
]
ExtractionMode = Literal["extract", "do_not_extract"]


class OntologyMapping(BaseModel):
    canonical_key: str
    # Human-readable name + a definition of what this canonical concept MEANS. The
    # definition/description is the primary signal for LLM description-based mapping: the
    # model matches a source caption to a concept by meaning, not string similarity.
    label: str = ""
    description: str = ""
    # Authoritative accounting definition (preferred over `description` when present) plus
    # natural-language inclusion / exclusion criteria and easily-confused concepts — all
    # fed to the LLM so the mapping decision is criteria-driven, not string-driven.
    # (Learnings from field-tested Ind-AS extraction ontologies.)
    definition: str = ""
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    confusable_with: list[str] = Field(default_factory=list)  # canonical_keys easy to confuse
    value_scope: ValueScope = "exclusive_leaf"
    extraction_mode: ExtractionMode = "extract"
    # Natural-language residual/decomposition rule for this concept (e.g. "= combined
    # intangible parent − goodwill − IAUD; if reported exclusively, do not subtract").
    decomposition_rule: str | None = None
    others_rule: str | None = None
    aliases: list[str] = Field(default_factory=list)          # default-locale aliases
    aliases_i18n: dict[str, list[str]] = Field(default_factory=dict)  # per-locale
    keyword_hints: list[str] = Field(default_factory=list)
    regex_hints: list[str] = Field(default_factory=list)
    exclude_hints: list[str] = Field(default_factory=list)
    sign_rule: SignRule = Field(default_factory=SignRule)
    note_ref_hint: NoteRefHint = Field(default_factory=NoteRefHint)
    min_confidence_to_auto_accept: float = 0.85

    def meaning(self) -> str:
        """Best available semantic text for description-based matching."""
        return self.definition or self.description or self.label or self.canonical_key

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


class NettingRule(BaseModel):
    """A face line whose reported value already INCLUDES other lines, to be netted out when
    showing the clean figure — e.g. a cost of sales that is stated inclusive of administrative
    and selling/marketing expenses. The net value is computed with signed arithmetic
    (``net = target − Σ subtract + Σ add``), so it works whether expenses are stored as
    negatives or positives, and the formula is surfaced alongside the value. Deterministic,
    non-destructive (the raw figure is kept and the adjustment is revertable), and admin-declared
    per template — never auto-applied, since containment is an entity/presentation judgement."""

    id: str
    target_key: str
    subtract_keys: list[str] = Field(default_factory=list)
    add_keys: list[str] = Field(default_factory=list)
    label: str = ""                         # human explanation of why the lines are contained


class GlobalRules(BaseModel):
    credit_balance_lines: list[str] = Field(default_factory=list)  # key globs
    paren_means_negative: bool = True
    # Natural-language extraction policies fed to the LLM system prompt so decisions
    # follow one consistent, auditable rulebook (learnings from prior ontologies):
    parent_child_allocation: list[str] = Field(default_factory=list)
    duplicate_fact_rule: str = ""      # face + note = one fact w/ multiple evidence
    other_income_rule: str = ""
    others_policy: list[str] = Field(default_factory=list)
    totals_policy: str = ""            # totals computed from mutually-exclusive outputs
    no_fabricated_split: str = ""
    source_fact_id: str = ""           # composition of the provenance identity


class WorkedExample(BaseModel):
    """A few-shot example injected into the mapping/extraction prompt to anchor policy."""

    scenario: str
    source: dict = Field(default_factory=dict)
    output: list[dict] = Field(default_factory=list)
    validation: str = ""
    instruction: str = ""


class OntologyMetadata(BaseModel):
    name: str = ""
    framework: str = ""                # e.g. IND_AS, HKFRS, IFRS
    version: str = ""
    source_template: str = ""
    field_count: int | None = None
    changes: list[str] = Field(default_factory=list)  # changelog


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
    metadata: OntologyMetadata | None = None
    mappings: list[OntologyMapping] = Field(default_factory=list)
    decomposition_rules: list[DecompositionRule] = Field(default_factory=list)
    # Face-line containment netting (e.g. cost of sales stated inclusive of admin / S&M).
    netting_rules: list[NettingRule] = Field(default_factory=list)
    global_rules: GlobalRules = Field(default_factory=GlobalRules)
    worked_examples: list[WorkedExample] = Field(default_factory=list)

    def number_format(self, locale: str | None) -> NumberFormat:
        if locale and locale in self.number_format_by_locale:
            return self.number_format_by_locale[locale]
        return self.number_format_by_locale.get("en", NumberFormat())

    def canonical_keys(self) -> set[str]:
        return {m.canonical_key for m in self.mappings}

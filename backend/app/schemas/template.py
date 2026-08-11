"""Template schema — the target output definition, authored/uploaded from the UI.

A template is an ordered section→node tree. Subtotal/total nodes declare a ``rollup``
listing exactly which children feed them, so subtotals can be *recomputed* and
compared to the extracted value (feeding the validation engine and review queue).
Statement-level ``identities`` (Assets = Liabilities + Equity) and set-level
``cross_statement_ties`` are declarative. Canonical labels carry ``label_i18n`` so
output can render in the same language set as input (multilingual parity).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.models.enums import LineRole, SignConvention, StatementType


class Rollup(BaseModel):
    op: Literal["sum", "diff", "weighted_sum"] = "sum"
    children: list[str] = Field(default_factory=list)  # node_ids


class TemplateNode(BaseModel):
    node_id: str
    canonical_key: str
    label: str
    label_i18n: dict[str, str] = Field(default_factory=dict)  # {"en": .., "zh": .., "ar": .., "fr": ..}
    role: LineRole = LineRole.LINE
    sign: SignConvention = SignConvention.NATURAL
    expects_note: bool = False
    required: bool = False
    children: list["TemplateNode"] = Field(default_factory=list)
    rollup: Rollup | None = None

    def resolve_label(self, locale: str | None) -> str:
        if locale and locale in self.label_i18n:
            return self.label_i18n[locale]
        return self.label_i18n.get("en", self.label)


class Identity(BaseModel):
    id: str
    lhs: str                                   # canonical_key / node_id
    rhs: Rollup                                # combination of terms
    tolerance_abs: float = 1.0
    tolerance_rel: float = 0.001


class TemplateStatement(BaseModel):
    type: StatementType
    default_sign_convention: SignConvention = SignConvention.NATURAL
    # The statement's own heading, per output language. Undeclared until now, but READ in two
    # places off the raw stored definition — ``documents._stmt_label`` and the Template screen's
    # tree via ``templates._loc(stmt, locale)`` — so it was authorable only by accident, and
    # refusing undeclared keys on upload turned "works but is not in the schema" into a 422 for
    # the one mechanism that gives a statement a localized heading at all. Without it every locale
    # falls back to the statement type titled ("Balance Sheet"), which is why the shipped
    # template's heading is untranslated on that screen today.
    label: str = ""
    label_i18n: dict[str, str] = Field(default_factory=dict)  # {"en": .., "zh": .., …}
    sections: list[TemplateNode] = Field(default_factory=list)
    identities: list[Identity] = Field(default_factory=list)

    def resolve_label(self, locale: str | None) -> str:
        if locale and locale in self.label_i18n:
            return self.label_i18n[locale]
        return self.label_i18n.get("en", self.label)


class CrossStatementTie(BaseModel):
    id: str
    lhs: dict                                  # {"statement": .., "key": ..}
    rhs: dict
    match_on: list[str] = Field(default_factory=lambda: ["basis", "period_end"])
    tolerance_abs: float = 1.0


class TemplateDefinition(BaseModel):
    schema_version: int = 1
    template_key: str
    name: str
    statements: list[TemplateStatement] = Field(default_factory=list)
    cross_statement_ties: list[CrossStatementTie] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_keys(self) -> "TemplateDefinition":
        keys = list(self.all_canonical_keys())
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"Duplicate canonical_key(s) in template: {sorted(dupes)}")
        return self

    def _walk(self, nodes: list[TemplateNode]):
        for n in nodes:
            yield n
            yield from self._walk(n.children)

    def all_nodes(self):
        for st in self.statements:
            yield from self._walk(st.sections)

    def all_canonical_keys(self) -> set[str]:
        return {n.canonical_key for n in self.all_nodes()}

    def node_ids(self) -> set[str]:
        return {n.node_id for n in self.all_nodes()}


TemplateNode.model_rebuild()

"""What an authored ontology has to look like — and a ready-to-edit one, built from a template.

Two things an author cannot otherwise find out. The SHAPE (:func:`json_schema`,
:func:`field_help`) is read straight off :class:`OntologyDefinition`, never transcribed, because
the same model is what the upload gate validates against: a hand-written field list would drift
from the gate the first time a field was added and then describe a contract the API does not
hold to. The SKELETON (:func:`build_skeleton`) is a complete, valid rulebook pre-filled from a
template — every canonical_key present as a stub, the section layer wired up — so authoring
starts from something that already passes the door instead of from a guess.

Since ``unknown_keys`` started refusing undeclared keys on upload, guessing costs a 422 per
attempt, and a *nearly* right skeleton is the expensive kind: :func:`build_skeleton` therefore
puts its own output through the gate's own two checks before returning it and raises rather than
serve one that would be rejected.
"""
from __future__ import annotations

import enum
import json
import types
import typing
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from app.core.models.enums import LineRole, StatementType
from app.schemas.loader import (
    load_ontology,
    unknown_keys,
    validate_ontology_against_template,
)
from app.schemas.ontology import (
    Binding,
    GlobalRules,
    Normalisation,
    NumberFormat,
    OntologyDefinition,
    OntologyMapping,
    OntologyMetadata,
    ResidualFramework,
    ScopeSelection,
    SectionDefaults,
    ValidationRules,
)
from app.schemas.template import TemplateDefinition, TemplateNode, TemplateStatement

# The version a NEW rulebook is authored at. Not ``OntologyDefinition.schema_version``'s default
# of 1: that default exists so the v1 files already in the database keep loading untouched, while
# anything authored now wants the section layer — without it ``section_scope``/``statement`` are
# authored on no concept at all and the section-first binding order has nothing to bind against.
CURRENT_SCHEMA_VERSION = 2

# The rank every ordinary concept starts at. Uniform, so nothing is pre-empted until an author
# deliberately raises one caption above its neighbours (higher is evaluated first).
_DEFAULT_MATCH_PRIORITY = 50


class SkeletonError(RuntimeError):
    """The generated skeleton would not survive the upload gate.

    Raised instead of returning it: the user's very first action with a downloaded skeleton is to
    upload it back, so one that 422s is worse than offering no download at all.
    """


# --- the shape ---------------------------------------------------------------------------------

# The three blocks an author writes by hand, expanded field by field: the definition root, the
# per-concept mapping, and the section layer a concept claims through ``inherits``. Everything
# reachable below them is named by its own entry (see ``_type_phrase``) rather than expanded, so
# the index stays flat enough to read in one pass.
_HELP_BLOCKS: tuple[tuple[type[BaseModel], str], ...] = (
    (OntologyDefinition, ""),
    (OntologyMapping, "mappings[]."),
    (SectionDefaults, "section_defaults.<section_id>."),
)

_NONE = type(None)
_UNIONS = (typing.Union, types.UnionType)
_SCALARS: dict[Any, str] = {str: "text", bool: "true | false", int: "whole number",
                            float: "number", dict: "object", list: "list"}


def _is_model(ann: Any) -> bool:
    return isinstance(ann, type) and issubclass(ann, BaseModel)


def _first_line(doc: str | None) -> str:
    """First line of a docstring, whitespace-collapsed; '' when there is none."""
    for line in (doc or "").strip().splitlines():
        if line.strip():
            return " ".join(line.split())
    return ""


def _as_json(value: Any) -> str:
    """A value spelled the way it has to be typed into the file, not the way Python prints it.

    ``True`` and ``'exclusive_leaf'`` are not what an author writes; ``true`` and
    ``"exclusive_leaf"`` are, and a help text that shows the other one invites a 422.
    """
    return json.dumps(value, default=str, ensure_ascii=False)


def _type_phrase(ann: Any) -> str:
    """A one-line rendering of an annotation, in the vocabulary the JSON actually uses."""
    origin, args = get_origin(ann), get_args(ann)
    if origin is Literal:
        return "one of " + " | ".join(_as_json(a) for a in args)
    if origin in _UNIONS:
        present = [a for a in args if a is not _NONE]
        phrase = " or ".join(_type_phrase(a) for a in present)
        # ``None`` on an optional field is not "false" or "empty" — it is the absence of a
        # statement, and the section layer folds on exactly that distinction.
        return phrase + ("; null = nothing said" if len(present) != len(args) else "")
    if origin is list:
        return f"list[{_type_phrase(args[0])}]" if args else "list"
    if origin is dict:
        return (f"object keyed by {_type_phrase(args[0])} of {_type_phrase(args[1])}"
                if args else "object")
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return "one of " + " | ".join(_as_json(m.value) for m in ann)
    if _is_model(ann):
        keys = ", ".join(f.alias or n for n, f in ann.model_fields.items())
        return f"{ann.__name__}{{{keys}}}"
    return _SCALARS.get(ann, getattr(ann, "__name__", str(ann)))


def _nested_doc(ann: Any) -> str:
    """The docstring of the model this field holds, through Optional / list / dict wrappers.

    That docstring is where the schema explains WHY a block exists (why a residual repeats the
    sweep terms, why ``with`` is aliased), which is the part an author cannot infer from the
    field name.
    """
    if _is_model(ann):
        return _first_line(ann.__doc__)
    args = [a for a in get_args(ann) if a is not _NONE]
    if get_origin(ann) is dict:
        args = args[1:]
    for arg in args:
        doc = _nested_doc(arg)
        if doc:
            return doc
    return ""


def field_help() -> list[dict]:
    """A flat path → help index of the fields an author fills in.

    Generated from the models, so a field added to the schema is described here the moment it
    exists and a renamed one cannot leave a stale path behind. The alternative — a curated list
    beside the models — is exactly the drift this endpoint exists to remove.
    """
    out: list[dict] = []
    for model, prefix in _HELP_BLOCKS:
        for name, field in model.model_fields.items():
            parts = [field.description or _nested_doc(field.annotation),
                     _type_phrase(field.annotation)]
            # A factory default is a fresh list/object — the type phrase already says so, and
            # printing "defaults to []" beside it adds nothing.
            if not field.is_required() and field.default_factory is None \
                    and field.default is not None:
                parts.append(f"defaults to {_as_json(field.default)}")
            out.append({
                "path": f"{prefix}{field.alias or name}",
                "required": field.is_required(),
                "help": " ".join(p for p in parts if p),
            })
    return out


def json_schema() -> dict:
    """The gate's own schema. Generated, so it cannot describe a contract the gate does not hold."""
    return OntologyDefinition.model_json_schema()


# --- the skeleton ------------------------------------------------------------------------------

# A balance sheet states positions AT a date; every other statement states movements OVER a
# period. That is the one thing about a concept's temporality the template already knows.
_INSTANT_STATEMENTS = frozenset({StatementType.BALANCE_SHEET})
# Headings carry no figure, and a subtotal is a figure a filing may print or leave to arithmetic
# — ``extract_or_derive`` keeps the printed row mappable instead of sweeping it into the residual.
_ROLE_OVERRIDES: dict[LineRole, dict[str, Any]] = {
    LineRole.HEADER: {"value_scope": "not_applicable", "extraction_mode": "do_not_extract"},
    LineRole.SPACER: {"value_scope": "not_applicable", "extraction_mode": "do_not_extract"},
    LineRole.SUBTOTAL: {"unit_of_account": "subtotal", "extraction_mode": "extract_or_derive"},
    LineRole.TOTAL: {"unit_of_account": "subtotal", "extraction_mode": "extract_or_derive"},
}


def _locales(template: TemplateDefinition) -> list[str]:
    """Every locale the template labels anything in, English first when present.

    The skeleton opens one alias slot per locale so an author can see which languages the
    template expects to be answered in, rather than discovering the gap at extraction time.
    """
    found: set[str] = set()
    for node in template.all_nodes():
        found.update(node.label_i18n)
    for stmt in template.statements:
        found.update(stmt.label_i18n)
    ordered = sorted(found - {"en"})
    return (["en"] if "en" in found or not ordered else []) + ordered


def _walk(node: TemplateNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def _top_level_section(stmt: TemplateStatement) -> str:
    """The section id for lines printed directly under a statement, owned by no banner.

    Statement-level totals ("Net assets", "Gross profit") sit beside the sections rather than
    inside one, and they still need a ``statement`` and a scope to be placeable — so they get a
    section of their own instead of being the only concepts the section layer never reaches.
    """
    return f"{stmt.type.value}_top_level"


def _section_defaults(stmt: TemplateStatement, section_id: str) -> dict:
    instant = stmt.type in _INSTANT_STATEMENTS
    return SectionDefaults(
        statement=stmt.type,
        section_scope=[section_id],
        temporality="instant" if instant else "duration",
        unit_of_account="balance" if instant else "flow",
        value_scope="exclusive_leaf",
        extraction_mode="extract",
        match_priority=_DEFAULT_MATCH_PRIORITY,
        # face_only / note_use / sign_convention are left unset on purpose. They are authoring
        # decisions, and on these fields ``null`` means "nothing was said" — writing a value the
        # author never chose would assert a policy the rulebook was not written for.
    ).model_dump()


def _stub(node: TemplateNode, section_id: str, locales: list[str]) -> dict:
    """One concept, carrying what the template knows and an empty slot for everything else."""
    stub: dict[str, Any] = {
        "canonical_key": node.canonical_key,
        "label": node.label,
        "inherits": section_id,
        # The criteria the mapper reasons over, in the order they are worth filling in: what the
        # concept MEANS first, then what it takes and refuses, then the lexical fallbacks.
        "definition": "",
        "include": [],
        "exclude": [],
        "confusable_with": [],
        "aliases": [],
        "aliases_i18n": {loc: [] for loc in locales},
        "keyword_hints": [],
        "regex_hints": [],
        "exclude_hints": [],
        # Carried over from the node rather than defaulted: the Template screen shows the
        # ontology's sign_rule in preference to the template's own hint, so a skeleton that
        # dropped it would blank the sign the template had already declared.
        "sign_rule": {"convention": node.sign.value, "flip_if_label_matches": []},
        "note_ref_hint": {"expects_note": node.expects_note},
    }
    stub.update(_ROLE_OVERRIDES.get(node.role, {}))
    return stub


def build_skeleton(template: TemplateDefinition, *, template_version: int | None = None) -> dict:
    """A complete, valid, ready-to-edit ontology for ``template``.

    Every canonical_key the template declares becomes a concept stub, each claiming the section
    it is printed under, so the file an author opens is already the right size and shape and the
    only work left is the part only they can do: aliases and criteria.

    Verified against the upload gate before it is returned — see :class:`SkeletonError`.
    """
    locales = _locales(template)
    sections: dict[str, dict] = {}
    mappings: list[dict] = []

    for stmt in template.statements:
        for top in stmt.sections:
            # A top-level node with children is a section BANNER; one without is a line that
            # belongs to the statement itself.
            section_id = top.node_id if top.children else _top_level_section(stmt)
            if section_id not in sections:
                sections[section_id] = _section_defaults(stmt, section_id)
            # The banner's own key gets a stub too, claiming the section it names, so the
            # skeleton accounts for EVERY canonical_key the template declares — an author
            # comparing counts should not have to work out which ones were dropped and why. Its
            # role marks it non-extractable (``_ROLE_OVERRIDES``), so being present costs nothing.
            for node in _walk(top):
                mappings.append(_stub(node, section_id, locales))

    skeleton = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        # Deliberately NOT the template's own key. Uploading under a live rulebook's key
        # publishes the next version OF it, and the Template screen and the language-parity page
        # both read the highest version — so an unfinished skeleton would become the rulebook
        # those pages describe. Renaming this is the author's first edit.
        "ontology_key": f"{template.template_key}_draft",
        "target_template_key": template.template_key,
        "target_template_version": template_version,
        "locale": locales[0] if locales else "en",
        "supported_locales": locales or ["en"],
        # A wrong decimal/thousands separator silently corrupts every value parsed under it, so
        # each supported locale gets its own explicit block instead of inheriting English.
        "number_format_by_locale": {loc: NumberFormat().model_dump() for loc in (locales or ["en"])},
        "metadata": OntologyMetadata(
            name=f"{template.name} — ontology skeleton",
            source_template=template.template_key,
            concept_count=len(mappings),
        ).model_dump(),
        "section_defaults": sections,
        "mappings": mappings,
        "decomposition_rules": [],
        "netting_rules": [],
        "worked_examples": [],
        # The policy blocks arrive at their documented defaults rather than absent: an author who
        # cannot see that a block exists cannot fill it in, and every key here is one the gate
        # accepts.
        "global_rules": GlobalRules().model_dump(),
        "normalisation": Normalisation().model_dump(),
        "binding": Binding().model_dump(),
        "scope_selection": ScopeSelection().model_dump(),
        "residual_framework": ResidualFramework().model_dump(),
        "validation": ValidationRules().model_dump(),
    }

    _verify(skeleton, template)
    return skeleton


def _verify(skeleton: dict, template: TemplateDefinition) -> None:
    """Put the skeleton through the checks ``POST /ontologies`` would apply to it.

    All three, because they fail differently: the model rejects a bad value, ``unknown_keys``
    rejects a key the schema does not declare (which pydantic would otherwise drop in silence,
    so a stub key typo'd here would go on being served forever), and the template cross-check
    rejects a concept the target template does not define. Resolution is exercised too — an
    ``inherits`` pointing at no section is a silent no-op on the read path and would leave every
    stub with no section at all.
    """
    try:
        ontology = load_ontology(skeleton)
        load_ontology(skeleton, resolve=True)
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim; this is a defect, not input
        raise SkeletonError(f"The generated skeleton is not a valid ontology: {exc}") from exc

    stray = unknown_keys(skeleton, ontology, limit=10)
    if stray:
        raise SkeletonError(
            "The generated skeleton carries keys the ontology schema does not declare, which the "
            f"upload gate would refuse: {stray}")

    errors = validate_ontology_against_template(ontology, template)
    if errors:
        raise SkeletonError(
            "The generated skeleton does not validate against its own template: "
            + "; ".join(f"{e.location}: {e.message}" for e in errors[:5]))

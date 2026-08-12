"""Load & validate template + ontology definitions.

The key cross-check: every ``canonical_key`` referenced by the ontology (in mappings
and decomposition rules) must resolve against the template, and every rollup/identity
must reference node_ids that exist. This is enforced on upload so a bad
template/ontology pairing is rejected with a clear list of offending keys.

A second check applies on UPLOAD ONLY: a key the schema does not declare is reported
(:func:`unknown_keys`) instead of being silently dropped. See that function for why the
strictness cannot live on the models themselves.

A ``schema_version: 2`` ontology also carries a SECTION LAYER — properties authored once per
section in ``section_defaults`` and claimed by a concept through ``inherits``.
:func:`resolve_inherits` folds it in, and it runs BEFORE validation: see that function for why
it cannot be a model validator.
"""
from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

from app.schemas.ontology import OntologyDefinition
from app.schemas.template import TemplateDefinition


class ValidationError(BaseModel):
    location: str
    message: str


class UnknownInheritsError(ValueError):
    """A concept's ``inherits`` names a ``section_defaults`` entry that does not exist."""


def load_template(data: dict) -> TemplateDefinition:
    return TemplateDefinition.model_validate(data)


def load_ontology(data: dict, *, resolve: bool = False) -> OntologyDefinition:
    """Validate an ontology definition.

    ``resolve=True`` folds the v2 section layer in first (:func:`resolve_inherits`) and is how a
    caller that intends to MATCH with the rulebook should load it. It is opt-in, and the default
    stays off, because the read path has other jobs — listing rulebooks, rendering the ontology
    editor, reading netting rules — where a concept's own declaration is the thing being shown and
    an inherited value silently merged into it would be wrong. It also keeps a stored definition
    with a broken ``inherits`` from turning those pages into a 500.
    """
    if resolve:
        data = resolve_inherits(data)
    return OntologyDefinition.model_validate(data)


def resolve_inherits(data: dict) -> dict:
    """Fold each ``section_defaults`` entry into every concept naming it via ``inherits``.

    A key declared ON THE CONCEPT always wins; the section supplies only what the concept is
    silent about. Returns a new definition dict — the input is left alone, because callers hand
    this the ``definition`` of a live DB row.

    Deliberately NOT a pydantic validator, for two reasons. Once validated, a concept that
    inherited ``match_priority`` is indistinguishable from one that declared it and from one that
    declared nothing at all (the model's default filled the field), so "declared wins" can only be
    decided on the raw dict — and the same is true of every optional field the section layer
    touches. And resolving before validation means the RESOLVED shape is what gets validated, so
    a section default with a bad value fails at the door rather than reaching a concept.

    Without this fold the section layer is inert: ``section_scope``, ``statement``,
    ``temporality`` and ``face_only`` are authored on no concept at all, so the section-first
    binding order the rulebook specifies would have nothing to bind against.
    """
    sections = data.get("section_defaults")
    mappings = data.get("mappings")
    # A v1 rulebook has no section layer; leaving it untouched is the whole point of the opt-in.
    if not isinstance(sections, dict) or not isinstance(mappings, list):
        return data

    resolved: list[Any] = []
    missing: list[str] = []
    for entry in mappings:
        if not isinstance(entry, dict) or "inherits" not in entry:
            resolved.append(entry)
            continue
        name = entry["inherits"]
        base = sections.get(name) if isinstance(name, str) else None
        if not isinstance(base, dict):
            # A silent no-op here is the failure this whole function exists to prevent, one level
            # up: the concept would validate, load, and quietly carry none of its section's
            # properties — no section_scope, so the binding order can never place it.
            # Collected rather than raised on the spot so one pass names every offender.
            missing.append(f"{entry.get('canonical_key', '?')} inherits {name!r}")
            continue
        # Deep-copied so the 12 concepts sharing a section do not share its `include` list.
        resolved.append({**copy.deepcopy(base), **entry})

    if missing:
        known = ", ".join(sorted(sections)) or "(none)"
        raise UnknownInheritsError(
            f"{len(missing)} concept(s) inherit a section_defaults entry that does not exist: "
            + "; ".join(missing[:10])
            + (f" (+{len(missing) - 10} more)" if len(missing) > 10 else "")
            + f". Declared sections: {known}"
        )
    return {**data, "mappings": resolved}


def unknown_keys(data: dict, model: BaseModel, *, limit: int = 40) -> list[str]:
    """Dotted paths of keys present in ``data`` that the schema does not declare.

    Pydantic's default is ``extra='ignore'``, so an undeclared key — a typo'd field name, or an
    ``inherits`` borrowed from some other tool's format — is dropped in silence: the definition
    publishes, reports success, and simply does not contain the thing that was authored. The
    author's next clue is an extraction that behaves as though the edit was never made.

    This is deliberately NOT ``model_config = ConfigDict(extra='forbid')`` on the models. The same
    two loaders read every definition already stored in the database, and those call sites do not
    all expect failure: ``languages.py`` has no handler at all (a 500), ``templates.py`` swallows
    the error and serves a silently emptied ontology, and the extraction worker swallows it into
    ``template = None``, which marks the run SUCCEEDED with every structural check quietly gone.
    Rejecting an undeclared key belongs at the door, where there is a request to fail and a person
    to tell; on the read path it would turn one bad row into an outage.

    Compares the input against a round-trip dump rather than introspecting the schema, so nested
    models, lists of models and ``dict[str, Model]`` fields all follow without special cases.
    ``limit`` caps the report — a definition authored against a wholly different format should say
    so in a sentence, not in nine hundred paths.
    """
    found: list[str] = []

    def walk(raw: Any, known: Any, path: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(raw, dict) and isinstance(known, dict):
            for k, v in raw.items():
                where = f"{path}.{k}" if path else str(k)
                if k not in known:
                    found.append(where)
                    continue
                walk(v, known[k], where)
        elif isinstance(raw, list) and isinstance(known, list):
            # A list the model parsed is element-for-element with its input; a list it coerced
            # from something else is a type error the validator has already reported.
            for i, (rv, kv) in enumerate(zip(raw, known)):
                walk(rv, kv, f"{path}[{i}]")

    walk(data, model.model_dump(), "")
    return found


def validate_template(template: TemplateDefinition) -> list[ValidationError]:
    errors: list[ValidationError] = []
    node_ids = template.node_ids()
    for st in template.statements:
        for ident in st.identities:
            for term in [ident.lhs, *ident.rhs.children]:
                if term not in node_ids and term not in template.all_canonical_keys():
                    errors.append(ValidationError(
                        location=f"identity:{ident.id}",
                        message=f"references unknown node/key {term!r}",
                    ))
        for node in template._walk(st.sections):
            if node.rollup:
                for child in node.rollup.children:
                    if child not in node_ids:
                        errors.append(ValidationError(
                            location=f"rollup:{node.node_id}",
                            message=f"references unknown node_id {child!r}",
                        ))
    return errors


def validate_ontology_against_template(
    ontology: OntologyDefinition, template: TemplateDefinition
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    template_keys = template.all_canonical_keys()

    for m in ontology.mappings:
        if m.canonical_key not in template_keys:
            errors.append(ValidationError(
                location=f"mapping:{m.canonical_key}",
                message="canonical_key does not exist in the target template",
            ))
    for rule in ontology.decomposition_rules:
        if rule.face_key not in template_keys:
            errors.append(ValidationError(
                location=f"decomposition:{rule.id}",
                message=f"face_key {rule.face_key!r} does not exist in the template",
            ))
    return errors


def validate_pair(
    template: TemplateDefinition, ontology: OntologyDefinition
) -> list[ValidationError]:
    return (
        validate_template(template)
        + validate_ontology_against_template(ontology, template)
    )

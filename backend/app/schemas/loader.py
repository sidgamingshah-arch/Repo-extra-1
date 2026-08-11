"""Load & validate template + ontology definitions.

The key cross-check: every ``canonical_key`` referenced by the ontology (in mappings
and decomposition rules) must resolve against the template, and every rollup/identity
must reference node_ids that exist. This is enforced on upload so a bad
template/ontology pairing is rejected with a clear list of offending keys.

A second check applies on UPLOAD ONLY: a key the schema does not declare is reported
(:func:`unknown_keys`) instead of being silently dropped. See that function for why the
strictness cannot live on the models themselves.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.ontology import OntologyDefinition
from app.schemas.template import TemplateDefinition


class ValidationError(BaseModel):
    location: str
    message: str


def load_template(data: dict) -> TemplateDefinition:
    return TemplateDefinition.model_validate(data)


def load_ontology(data: dict) -> OntologyDefinition:
    return OntologyDefinition.model_validate(data)


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

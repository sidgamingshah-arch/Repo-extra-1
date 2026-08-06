"""Load & validate template + ontology definitions.

The key cross-check: every ``canonical_key`` referenced by the ontology (in mappings
and decomposition rules) must resolve against the template, and every rollup/identity
must reference node_ids that exist. This is enforced on upload so a bad
template/ontology pairing is rejected with a clear list of offending keys.
"""
from __future__ import annotations

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

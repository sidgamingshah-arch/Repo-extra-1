from __future__ import annotations

from .languages import LanguageParity, evaluate_parity
from .loader import (
    ValidationError,
    load_ontology,
    load_template,
    validate_ontology_against_template,
    validate_pair,
    validate_template,
)
from .ontology import OntologyDefinition
from .template import TemplateDefinition

__all__ = [
    "TemplateDefinition",
    "OntologyDefinition",
    "LanguageParity", "evaluate_parity",
    "ValidationError", "load_template", "load_ontology",
    "validate_template", "validate_ontology_against_template", "validate_pair",
]

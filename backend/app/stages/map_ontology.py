"""Ontology-mapping stage — applies the multi-strategy matching ensemble.

Wires each extracted ``LineItem`` through ``services.mapping.OntologyMatcher`` and
records the winning canonical key, method, and per-strategy confidence. The ontology
+ locale come from the extraction job; adapters (embedding/LLM) are pulled from the
registry when configured.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext
from app.services.mapping import OntologyMatcher


class MapOntologyStage:
    name = "map_ontology"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        ontology = getattr(ctx, "ontology", None)
        if ontology is None or not doc.line_items:
            ctx.log("map_ontology:skipped(no ontology or no line items)")
            return doc

        matcher = OntologyMatcher(ontology, locale=doc.locale, settings=ctx.settings)
        mapped = 0
        for li in doc.line_items:
            result = matcher.match(li.source_label)
            if result.canonical_key:
                li.canonical_key = result.canonical_key
                li.confidence.mapping = result.confidence
                li.confidence.method = result.method.value
                if result.needs_review:
                    li.confidence.flags.append("low_mapping_confidence")
                mapped += 1
        ctx.log(f"map_ontology:mapped={mapped}/{len(doc.line_items)}")
        return doc

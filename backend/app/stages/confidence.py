"""Confidence + validation stage.

Combines the confidence vector for each value and runs the validation rules
(subtotal rollups, balance-sheet identity, cross-statement ties, note ties,
confidence thresholds), emitting review-queue items for failures. The
``ConfidenceVector.overall`` combination is implemented on the model; the validation
engine is TODO (see docs/architecture — RuleDefinition/RuleResult).
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext


class ConfidenceStage:
    name = "confidence"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        # TODO: run RuleDefinition catalog -> RuleResult -> ReviewItem; set
        #       ExtractedValue.confidence.validation to modulate overall.
        ctx.log(f"confidence:line_items={len(doc.line_items)}")
        return doc

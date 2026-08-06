"""Sign & unit normalization stage.

Detects value polarity (parentheses/"less:"/Excel number-format/red text/column
context) and normalizes to the ontology ``sign_convention``; resolves unit context at
the most-specific scope. The parentheses/minus tier already lives in
``services.numbers``; the remaining signals and unit resolution are TODO.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext


class NormalizeStage:
    name = "normalize"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        # TODO: apply ontology sign_rule (flip_if_label_matches), "less:/add:" cues,
        #       Excel number-format sign, and resolve unit contexts per scope.
        ctx.log("normalize:todo")
        return doc

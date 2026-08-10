"""Pipeline orchestrator.

Runs an ordered list of stages, each enriching the document model. A BLOCKER
integrity finding short-circuits the remaining stages (extraction can't proceed on
a corrupt/encrypted document), but everything else runs to completion so partial
results and all findings are available.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.models import DocumentModel
from app.core.stage import PipelineContext, Stage


@dataclass
class Pipeline:
    stages: list[Stage] = field(default_factory=list)

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        n = len(self.stages)
        for i, stage in enumerate(self.stages):
            ctx.emit_progress(stage.name, round(i / max(n, 1), 3))
            ctx.log(f"stage:{stage.name}:start")
            doc = stage.run(doc, ctx)
            ctx.log(f"stage:{stage.name}:done")

            # Short-circuit only on a hard blocker discovered by the integrity stage.
            if doc.integrity is not None and doc.integrity.has_blockers:
                ctx.log("pipeline:halted:integrity_blocker")
                break
        ctx.emit_progress("done", 1.0)
        return doc


def default_pipeline() -> Pipeline:
    """Assemble the default native-path pipeline.

    Imported lazily to avoid a circular import (stages import core models).
    """
    from app.stages.ingest import IngestStage
    from app.stages.integrity import IntegrityStage
    from app.stages.language import LanguageDetectStage
    from app.stages.classify import ClassifyStage
    from app.stages.extract import ExtractStage
    from app.stages.map_ontology import MapOntologyStage
    from app.stages.normalize import NormalizeStage
    from app.stages.link_notes import LinkNotesStage
    from app.stages.reconcile import ReconcileStage
    from app.stages.confidence import ConfidenceStage

    # Table reconstruction is performed inside the extract stage (native pages via the
    # PyMuPDF text layer + shared row_reconstruct; scanned pages via the OCR port), so there
    # is no separate reconstruct stage — extraction consumes the reconstruction directly.
    return Pipeline(stages=[
        IngestStage(),
        IntegrityStage(),
        LanguageDetectStage(),
        ClassifyStage(),
        ExtractStage(),
        MapOntologyStage(),
        NormalizeStage(),
        LinkNotesStage(),
        ReconcileStage(),
        ConfidenceStage(),
    ])

"""Segment the finished document into the eight analyst buckets.

LAST IN THE PIPELINE, and the position is the design. The buckets an analyst asks for are four
balance-sheet sections plus equity, and a balance sheet prints all five on one page — so page
classification, which answers "which statement is this", can never separate them. Only a row's own
resolved section can, which means this runs after mapping and after the residual sweep has given
every printed row somewhere to be.

The stage computes nothing an earlier stage already knows: it reads sections and statements that
already exist and records WHICH BUCKET each row and note belongs to. See ``services.buckets`` for
the resolution rule and for what deliberately lands in Others.
"""
from __future__ import annotations

from app.core.models import DocumentModel
from app.core.stage import PipelineContext
from app.services.buckets import segment_source


class SegmentStage:
    name = "segment"

    def run(self, doc: DocumentModel, ctx: PipelineContext) -> DocumentModel:
        ontology = getattr(ctx, "ontology", None)
        doc.buckets = segment_source(doc, ontology)
        placed = sum(len(s.face_item_ids) for s in doc.buckets.segments)
        notes = sum(len(s.note_numbers) for s in doc.buckets.segments)
        ctx.log(f"segment:placed({placed} face rows, {notes} notes)")
        for seg in doc.buckets.segments:
            if seg.face_item_ids or seg.note_numbers:
                ctx.log(f"segment:{seg.bucket}({len(seg.face_item_ids)} rows, "
                        f"{len(seg.note_numbers)} notes)")
        if doc.buckets.unresolved_face_item_ids:
            ctx.log(f"segment:unresolved({len(doc.buckets.unresolved_face_item_ids)} face rows "
                    "reached Others because nothing could place them)")
        for section in doc.buckets.unknown_sections:
            # A whole section of a filing with no bucket to hold it. Loud, because the rows are in
            # Others and a reader summing the buckets would see a total that ties and a section
            # that is missing from every view.
            ctx.log(f"segment:unknown_section({section})")
        return doc

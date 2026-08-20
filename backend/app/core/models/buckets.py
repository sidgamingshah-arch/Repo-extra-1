"""The eight analyst buckets a filing's source is segmented into, and what each one holds.

WHY A SEGMENTATION AND NOT A COPY. Each segment names the face rows, notes and pages that belong
to its bucket; it does not carry their figures. A figure stored twice is two places computing one
quantity, and here the copy would be the one an analyst reads — so the membership is persisted and
the API joins it to ``line_items`` at serve time. What is new information (which content belongs to
which bucket) is stored; what already exists (the numbers) is referenced.

EVERY ROW LANDS IN EXACTLY ONE BUCKET. That is the property that makes the store safe to sum, and
``unresolved_face_item_ids`` is what stops "everything is placed" from being achieved by sweeping
the difficult cases into Others unnoticed: rows in Others because the balance sheet's own totals
span sections are a different fact from rows in Others because nothing could place them, and only
the second is a coverage failure.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BucketSegment(BaseModel):
    """One bucket's membership. Ids and numbers, never figures — see the module docstring."""

    bucket: str
    label: str
    # Face rows printed on a statement face and resolved to this bucket.
    face_item_ids: list[str] = Field(default_factory=list)
    # Notes whose PRIMARY bucket is this one. A note cited from two buckets is filed once, under
    # the bucket that cites it most, and named in the other's ``shared_notes`` — storing it twice
    # would double every figure it contains for any reader that sums the buckets.
    note_numbers: list[str] = Field(default_factory=list)
    # Notes filed under a DIFFERENT bucket that a face row in this one cites. Read-only pointers.
    shared_notes: list[str] = Field(default_factory=list)
    face_pages: list[int] = Field(default_factory=list)
    note_pages: list[int] = Field(default_factory=list)
    # The template ``section_scope`` ids that resolved into this bucket, so a reader can see WHY
    # a row is here without re-deriving the rule.
    sections: list[str] = Field(default_factory=list)


class BucketedSource(BaseModel):
    """The whole segmentation, in the order the buckets are presented."""

    segments: list[BucketSegment] = Field(default_factory=list)
    # Face rows that reached Others because nothing could place them — not because they belong
    # there. A coverage fact, measurable across a corpus.
    unresolved_face_item_ids: list[str] = Field(default_factory=list)
    unresolved_note_numbers: list[str] = Field(default_factory=list)
    # A template section this vocabulary has no bucket for. Its rows are in Others and this names
    # the section, because a taxonomy that silently swallows a whole section of a filing reads
    # exactly like one that covers it.
    unknown_sections: list[str] = Field(default_factory=list)

    def segment(self, bucket: str) -> BucketSegment | None:
        return next((s for s in self.segments if s.bucket == bucket), None)

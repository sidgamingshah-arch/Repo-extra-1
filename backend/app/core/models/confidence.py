"""Confidence vector.

Per-extraction confidence is kept as a *vector* of independent sub-confidences
(OCR, structure, mapping, validation) — not just a scalar — so the UI can colour
individual attributes and the review queue can sort by the weakest component and
explain *why* a value is doubtful.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ConfidenceVector(BaseModel):
    ocr: float = Field(default=1.0, ge=0.0, le=1.0)
    structure: float = Field(default=1.0, ge=0.0, le=1.0)
    mapping: float = Field(default=1.0, ge=0.0, le=1.0)
    sign: float = Field(default=1.0, ge=0.0, le=1.0)
    note_link: float = Field(default=1.0, ge=0.0, le=1.0)
    validation: float | None = None  # set after validation; modulates overall

    method: str | None = None        # winning mapping method
    flags: list[str] = Field(default_factory=list)

    @property
    def overall(self) -> float:
        """Multiplicative combination of the core signals, modulated by validation.

        Validation acts as a corrector: a hard balance failure caps the score low
        regardless of clean OCR; a confirmed reconciling total can only *lower* the
        product here (never fabricate confidence), so a failed check dominates.
        """
        base = self.ocr * self.structure * self.mapping
        if self.validation is not None:
            base *= self.validation
        return round(base, 4)

    @property
    def weakest(self) -> float:
        vals = [self.ocr, self.structure, self.mapping, self.sign, self.note_link]
        if self.validation is not None:
            vals.append(self.validation)
        return round(min(vals), 4)

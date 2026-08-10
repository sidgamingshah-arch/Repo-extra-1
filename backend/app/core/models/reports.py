"""Result/report models emitted by the reconcile and validation stages."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from .enums import Severity


class ReconciliationEntry(BaseModel):
    face_item_id: str
    note_number: str
    basis: str
    period_label: str | None = None
    raw_face: Decimal
    subtracted: Decimal
    reconciled: Decimal
    residual: Decimal
    within_tolerance: bool
    # "tied" | "untied" | "unconfirmed" — see app.services.reconcile. Only "untied" is a
    # discrepancy worth an analyst's time; "unconfirmed" means the note is not a breakdown
    # of this face figure, which is the normal case for an analysis or segment note.
    tie_status: str = "unconfirmed"
    relationship: str


class ReconciliationReport(BaseModel):
    entries: list[ReconciliationEntry] = Field(default_factory=list)
    failed_assertions: list[str] = Field(default_factory=list)


class RuleResult(BaseModel):
    rule_id: str
    kind: str
    scope_key: str
    status: str                      # pass | fail | skipped | error
    expected: Decimal | None = None
    actual: Decimal | None = None
    difference: Decimal | None = None
    details: dict = Field(default_factory=dict)


class StructuralReport(BaseModel):
    """Template-structure validation (rollups + declared identities) as ``RuleResult`` rows.

    Both outcomes are kept: a relation actually checked (``pass``/``fail``) and one that could
    not be checked because a participant was never extracted (``skipped``, with the reason).
    Keeping the skips is the honest half — it says how much of the structure a run could
    verify, so a nearly-unverified extraction can't read as a clean one.
    """

    results: list[RuleResult] = Field(default_factory=list)
    failed_assertions: list[str] = Field(default_factory=list)

    def evaluated(self) -> list[RuleResult]:
        return [r for r in self.results if r.status in ("pass", "fail")]

    def failures(self) -> list[RuleResult]:
        return [r for r in self.results if r.status == "fail"]

    def skipped(self) -> list[RuleResult]:
        return [r for r in self.results if r.status == "skipped"]


class ReviewItemModel(BaseModel):
    rule_id: str
    category: str
    severity: Severity
    target_type: str
    target_id: str
    expected: Decimal | None = None
    actual: Decimal | None = None
    difference: Decimal | None = None
    message: str
    scope_key: str

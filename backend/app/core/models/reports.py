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

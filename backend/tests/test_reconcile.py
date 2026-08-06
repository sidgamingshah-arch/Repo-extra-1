"""Tests for the note→face reconciliation arithmetic (Requirement 20)."""
from __future__ import annotations

from decimal import Decimal

from app.services.reconcile import NoteDetail, ReconcileInput, reconcile_face


def test_one_to_one_subtraction():
    # Face PPE = 12,800; note details (already ingested as their own lines) sum to it.
    inp = ReconcileInput(
        face_item_id="ppe",
        note_number="5",
        raw_face_value=Decimal("12800"),
        details=[
            NoteDetail("gross_block", Decimal("15000")),
            NoteDetail("acc_depreciation", Decimal("-2200")),
        ],
    )
    out = reconcile_face(inp)
    assert out.subtracted == Decimal("12800")
    assert out.reconciled == Decimal("0")     # fully explained by the note
    assert out.residual == Decimal("0")
    assert out.within_tolerance


def test_partial_leaves_residual():
    inp = ReconcileInput(
        face_item_id="investments",
        note_number="6",
        raw_face_value=Decimal("5000"),
        details=[NoteDetail("quoted", Decimal("3000"))],  # only part mapped
    )
    out = reconcile_face(inp)
    assert out.subtracted == Decimal("3000")
    assert out.reconciled == Decimal("2000")   # the residual "other" component
    assert out.residual == Decimal("2000")


def test_negative_signed_detail_subtracted_with_sign():
    inp = ReconcileInput(
        face_item_id="net_block",
        note_number="5",
        raw_face_value=Decimal("12800"),
        details=[NoteDetail("acc_depreciation", Decimal("-2200"))],
    )
    out = reconcile_face(inp)
    # subtracting a negative adds back: 12800 - (-2200) = 15000
    assert out.reconciled == Decimal("15000")


def test_dedupe_prevents_double_subtraction():
    inp = ReconcileInput(
        face_item_id="x",
        note_number="9",
        raw_face_value=Decimal("100"),
        details=[NoteDetail("a", Decimal("40")), NoteDetail("a", Decimal("40"))],
    )
    out = reconcile_face(inp)
    assert out.subtracted == Decimal("40")     # duplicate ignored
    assert any("duplicate" in w for w in out.warnings)


def test_idempotent_from_raw():
    inp = ReconcileInput(
        face_item_id="x", note_number="1", raw_face_value=Decimal("500"),
        details=[NoteDetail("a", Decimal("200"))],
    )
    first = reconcile_face(inp)
    second = reconcile_face(inp)   # recomputed from raw, never from reconciled
    assert first.reconciled == second.reconciled == Decimal("300")


def test_negative_reconciled_is_flagged():
    inp = ReconcileInput(
        face_item_id="x", note_number="1", raw_face_value=Decimal("100"),
        details=[NoteDetail("a", Decimal("250"))],
    )
    out = reconcile_face(inp)
    assert out.reconciled == Decimal("-150")
    assert any("negative" in w for w in out.warnings)

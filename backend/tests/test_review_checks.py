"""Real validation checks feed the review queue (Req 11): balance identity and note ties,
plus the ConfidenceStage setting the validation sub-signal."""
from __future__ import annotations


def _row(key, cur):
    return {"canonical_key": key,
            "values": [{"basis": "consolidated", "period_label": "current", "value": str(cur)}]}


def test_accounting_checks_flag_balance_and_note_ties():
    from app.api.routes.documents import _accounting_checks

    rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 90)]
    recon = [{"note_number": "9", "basis": "consolidated", "period_label": "current",
              "raw_face": 1000, "residual": 250, "within_tolerance": False}]
    checks = _accounting_checks(rows, recon, "en")
    types = {c["type"] for c in checks}
    assert "balance" in types and "note_tie" in types
    bal = next(c for c in checks if c["type"] == "balance")
    assert bal["delta"] == "10"

    # A balanced sheet with tying notes yields no accounting checks.
    ok_rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 100)]
    ok_recon = [{"note_number": "9", "basis": "consolidated", "period_label": "current",
                 "raw_face": 1000, "residual": 0, "within_tolerance": True}]
    assert _accounting_checks(ok_rows, ok_recon, "en") == []


def test_review_queue_includes_failed_checks():
    from app.api.routes.documents import _build_review

    rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 90)]
    review = _build_review(rows, "doc.pdf", "en",
                           [{"note_number": "9", "basis": "consolidated", "period_label": "current",
                             "raw_face": 1000, "residual": 250, "within_tolerance": False}])
    assert any(t["label"] == "Checks" and t["count"] == 2 for t in review["tabs"])
    assert any(c["type"] == "balance" for c in review["checks"])


def test_confidence_stage_sets_validation_on_balance_mismatch():
    from app.core.models.document import DocumentModel
    from app.core.models.enums import Basis
    from app.core.models.line_item import ExtractedValue, LineItem
    from app.core.stage import PipelineContext
    from app.stages.confidence import ConfidenceStage

    def li(key, val):
        item = LineItem(canonical_key=key)
        item.set_value(ExtractedValue(value=val, value_raw=val, basis=Basis.CONSOLIDATED,
                                      period_label="current"))
        return item

    doc = DocumentModel(filename="x.pdf")
    doc.line_items = [li("bs_total_assets", 100), li("bs_total_equity_and_liabilities", 90)]
    ConfidenceStage().run(doc, PipelineContext(raw_bytes=b""))
    ev = next(iter(doc.line_items[0].values.values()))
    assert ev.confidence.validation == 0.4 and "balance_mismatch" in ev.confidence.flags
    assert ev.confidence.overall < ev.confidence.mapping   # validation caps overall

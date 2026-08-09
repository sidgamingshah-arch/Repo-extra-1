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


def test_per_value_confidence_exposed(client):
    """Each extracted value carries its own confidence vector (mapping/validation/overall/
    weakest + flags), not just a single per-row number (Req 9)."""
    import time

    from tests.fixtures.generate import make_native_pdf

    doc_id = client.post("/api/v1/documents",
                         files={"file": ("bs.pdf", make_native_pdf(), "application/pdf")}).json()["id"]
    onts = client.get("/api/v1/ontologies").json()
    ont = next((o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v1"), onts[0])
    tpls = client.get("/api/v1/templates").json()
    tpl = next((t for t in tpls if t["template_key"] == ont["target_template_key"]), tpls[0])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    for _ in range(100):
        if client.get(f"/api/v1/documents/{doc_id}/run").json().get("status") == "succeeded":
            break
        time.sleep(0.05)

    rows = client.get(f"/api/v1/documents/{doc_id}/run").json()["result"]["rows"]
    valued = next(r for r in rows if r.get("values"))
    conf = valued["values"][0]["confidence"]
    assert {"mapping", "validation", "overall", "weakest", "flags"} <= set(conf)
    assert isinstance(conf["overall"], (int, float)) and 0.0 <= conf["overall"] <= 1.0
    assert isinstance(conf["flags"], list)

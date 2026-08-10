"""Real validation checks feed the review queue (Req 11): balance identity and note ties,
plus the ConfidenceStage setting the validation sub-signal."""
from __future__ import annotations


def _row(key, cur):
    return {"canonical_key": key,
            "values": [{"basis": "consolidated", "period_label": "current", "value": str(cur)}]}


def _recon(residual, *, face=1000, note="9", **extra):
    ent = {"note_number": note, "basis": "consolidated", "period_label": "current",
           "raw_face": face, "residual": residual, "within_tolerance": residual == 0}
    ent.update(extra)
    return ent


def test_accounting_checks_flag_balance_and_note_ties():
    from app.api.routes.documents import _accounting_checks

    rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 90)]
    # 2% off the face figure: unmistakably the same quantity, so a real discrepancy.
    checks = _accounting_checks(rows, [_recon(20)], "en")
    types = {c["type"] for c in checks}
    assert "balance" in types and "note_tie" in types
    bal = next(c for c in checks if c["type"] == "balance")
    assert bal["delta"] == "10"

    # A balanced sheet with tying notes yields no accounting checks.
    ok_rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 100)]
    assert _accounting_checks(ok_rows, [_recon(0)], "en") == []


def test_a_note_that_is_not_a_breakdown_of_the_face_figure_is_not_a_finding():
    """Most cited notes are not decompositions — an analysis of profit before tax, a segment
    table, a commitments schedule. Their totals are nowhere near the face figure, and asserting
    "does not tie" against them buries the real findings (it produced 246 non-findings on a
    single real filing)."""
    from app.api.routes.documents import _accounting_checks

    rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 100)]
    assert _accounting_checks(rows, [_recon(250)], "en") == []          # 25% off
    assert _accounting_checks(rows, [_recon(-15_645_284_739, face=88_611)], "en") == []


def test_one_finding_per_note_basis_and_period():
    """A note spanning several tables (continuation pages, sub-analyses) asks one question."""
    from app.api.routes.documents import _accounting_checks

    rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 100)]
    dupes = [_recon(20), _recon(21), _recon(22)]
    ties = [c for c in _accounting_checks(rows, dupes, "en") if c["type"] == "note_tie"]
    assert len(ties) == 1


def test_the_grade_is_derived_for_runs_stored_before_it_existed():
    """An older run carries only within_tolerance; the grade is determinable from the stored
    numbers, so those runs report correctly without re-extraction."""
    from app.services.reconcile import tie_status

    assert tie_status({"raw_face": 1000, "residual": 0, "within_tolerance": True}) == "tied"
    assert tie_status({"raw_face": 1000, "residual": 20, "within_tolerance": False}) == "untied"
    assert tie_status({"raw_face": 1000, "residual": 250,
                       "within_tolerance": False}) == "unconfirmed"
    # An explicit grade always wins over the derivation.
    assert tie_status({"raw_face": 1000, "residual": 250, "tie_status": "untied"}) == "untied"


def test_review_queue_includes_failed_checks():
    from app.api.routes.documents import _build_review

    rows = [_row("bs_total_assets", 100), _row("bs_total_equity_and_liabilities", 90)]
    review = _build_review(rows, "doc.pdf", "en", [_recon(20)])
    assert any(t["label"] == "Checks" and t["count"] == 2 for t in review["tabs"])
    assert any(c["type"] == "balance" for c in review["checks"])


def test_the_balance_identity_runs_when_the_filing_never_prints_the_totals():
    """HK/PRC statements often print no "Total assets" line at all — they run the section
    subtotals and "Total assets less current liabilities". Requiring the printed total meant
    the identity check silently never ran on exactly those filings."""
    from app.api.routes.documents import _accounting_checks

    rows = [_row("bs_non_current_assets__total_non_current_assets", 60),
            _row("bs_current_assets__total_current_assets", 40),
            _row("bs_equity__total_equity", 25),
            _row("bs_non_current_liabilities__total_non_current_liabilities", 30),
            _row("bs_current_liabilities__total_current_liabilities", 50)]   # 100 vs 105
    bal = next(c for c in _accounting_checks(rows, [], "en") if c["type"] == "balance")
    assert bal["delta"] == "-5"
    assert any("derived" in str(line[0]).lower() for line in bal["calc"])

    # ...and it passes silently when the derived sides agree.
    rows[-1] = _row("bs_current_liabilities__total_current_liabilities", 45)
    assert _accounting_checks(rows, [], "en") == []


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


def test_several_printed_lines_mapping_to_one_concept_are_summed_not_dropped():
    """Concepts legitimately absorb more than one printed line — three depreciation lines roll
    into "Depreciation and amortisation", two tax payments into "Income tax paid", and an
    "Others" bucket exists to catch a handful. Showing only the first would drop the rest from
    the statement with nothing to indicate a figure went missing."""
    from app.api.routes.documents import _build_statement

    key = "cf_cash_flow_from_operating_activities__income_tax_paid"
    rows = [
        {"canonical_key": key, "source_label": "PRC corporate income tax paid",
         "values": [{"basis": "consolidated", "period_label": "current", "value": "-559917"}]},
        {"canonical_key": key, "source_label": "PRC land appreciation tax paid",
         "values": [{"basis": "consolidated", "period_label": "current", "value": "-44488"}]},
    ]
    stmt = _build_statement(rows, None, "cash_flow", "f.pdf")
    row = next(r for r in stmt["rows"] if r["id"] == key)
    assert row["v1"] == -604405                      # both lines, not just the first
    assert "Sum of 2 printed lines" in row["inspector"]["note"]
    assert "land appreciation" in row["inspector"]["note"]


def test_a_concept_with_one_source_line_is_unchanged():
    from app.api.routes.documents import _build_statement

    key = "cf_cash_flow_from_operating_activities__income_tax_paid"
    rows = [{"canonical_key": key, "source_label": "Income tax paid",
             "values": [{"basis": "consolidated", "period_label": "current", "value": "-100"}]}]
    row = next(r for r in _build_statement(rows, None, "cash_flow", "f.pdf")["rows"]
               if r["id"] == key)
    assert row["v1"] == -100 and "Sum of" not in row["inspector"]["note"]

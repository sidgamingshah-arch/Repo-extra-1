"""Note→face reconciliation wired end-to-end (Requirement 20): the pipeline builds
face↔note links, the reconcile stage ties the note total back to the face figure and
writes the reconciled value, and the result surfaces on the notes endpoint, the export,
and the checks engine."""
from __future__ import annotations

import io
import time

import pytest

pytest.importorskip("fitz")

from tests.fixtures.generate import make_multipage_pdf


def _await_run(client, doc_id: str) -> dict:
    for _ in range(100):
        r = client.get(f"/api/v1/documents/{doc_id}/run")
        if r.status_code == 200 and r.json().get("status") == "succeeded":
            return r.json()["result"]
        time.sleep(0.05)
    raise AssertionError("extraction did not finish")


def test_reconcile_stage_links_and_ties_note_to_face():
    from app.services.documents import run_extraction

    doc, _ = run_extraction(make_multipage_pdf(), filename="multi.pdf")
    assert doc.links, "expected a face↔note link built from the 'Note 14' reference"
    assert doc.reconciliation is not None and doc.reconciliation.entries
    e = next(e for e in doc.reconciliation.entries if e.note_number == "14")
    # Face cash 1,204 == note detail 204 + 1,000 → ties, residual 0.
    assert e.raw_face == 1204 and e.residual == 0 and e.within_tolerance
    # Reconciled written back onto the face value (idempotent; from raw).
    cash = next(li for li in doc.line_items if "Cash" in li.source_label)
    ev = next(iter(cash.values.values()))
    assert ev.reconciled == 1204


def test_reconciliation_surfaces_on_notes_endpoint_and_export(client):
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("multi.pdf", make_multipage_pdf(), "application/pdf")}
    ).json()["id"]
    onts = client.get("/api/v1/ontologies").json()
    ont = next((o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v1"), onts[0])
    tpls = client.get("/api/v1/templates").json()
    tpl = next((t for t in tpls if t["template_key"] == ont["target_template_key"]), tpls[0])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    result = _await_run(client, doc_id)
    assert result["reconciliation"], "reconciliation entries should be stored on the run"

    detail = client.get(f"/api/v1/documents/{doc_id}/notes/14").json()
    assert detail["reconciliation"] and "tie" in detail["reconciliation"].lower()

    import openpyxl
    x = client.get(f"/api/v1/documents/{doc_id}/export",
                   params={"fmt": "excel", "layout": "statement"})
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    text = " | ".join(str(v) for row in wb["Note details"].iter_rows(values_only=True)
                      for v in row if v)
    assert "Reconciliation" in text and "residual" in text.lower()


def test_check_reconciliation_flags_untied_notes():
    from app.services.checks import check_reconciliation

    ok = check_reconciliation([{"note_number": "14", "basis": "consolidated",
                                "period_label": "current", "raw_face": 1204,
                                "residual": 0, "within_tolerance": True}])
    assert ok[0].status == "pass" and ok[0].type == "note_tie"
    bad = check_reconciliation([{"note_number": "9", "basis": "consolidated",
                                 "period_label": "current", "raw_face": 1000,
                                 "residual": 20, "within_tolerance": False}])
    assert bad[0].status == "fail" and bad[0].delta == 20

    # A note whose total is nowhere near the face figure is not a breakdown of it, so there is
    # nothing to pass or fail — it produces no check at all.
    assert check_reconciliation([{"note_number": "8", "basis": "consolidated",
                                  "period_label": "current", "raw_face": 1000,
                                  "residual": 250, "within_tolerance": False}]) == []

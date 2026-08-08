"""PDF extraction: native text layer (PyMuPDF) and the scanned/OCR path — both producing
line items with page + normalized-bbox provenance."""
from __future__ import annotations

import pytest

pytest.importorskip("fitz")

from tests.fixtures.generate import make_native_pdf


def test_native_pdf_extracts_values_with_bbox_provenance():
    from app.core.models.enums import Basis
    from app.services.documents import run_extraction

    doc, ctx = run_extraction(make_native_pdf(), filename="bs.pdf")
    assert doc.fmt.value == "pdf"
    labels = {li.source_label for li in doc.line_items}
    assert any("Trade receivables" in lbl for lbl in labels)

    tr = next(li for li in doc.line_items if "Trade receivables" in li.source_label)
    val = tr.get_value(Basis.CONSOLIDATED, period_label="current")
    assert val is not None and int(val.value) == 3410      # "3,410" parsed
    assert val.provenance is not None and val.provenance.page_index == 0
    assert val.provenance.bbox is not None                  # real click-to-source geometry
    assert val.provenance.source_kind == "native"
    assert tr.note_number == "15"                           # "Note 15" captured, not a value


def test_extraction_api_returns_rows_with_provenance(client):
    """Upload → run extraction → the run result carries view-ready rows + provenance."""
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("bs.pdf", make_native_pdf(), "application/pdf")}
    ).json()["id"]
    r = client.post(f"/api/v1/documents/{doc_id}/extractions", json={})
    assert r.status_code == 202, r.text
    rows = r.json()["result"]["rows"]
    assert rows and any(row["values"] for row in rows)
    tr = next(row for row in rows if "Trade receivables" in row["source_label"])
    prov = tr["values"][0]["provenance"]
    assert prov["source_kind"] == "native" and prov["page_index"] == 0 and prov["bbox"]
    assert tr["note"] == "15"


def test_document_integrity_endpoint_shapes_real_report(client):
    """A real uploaded file surfaces its own pre-flight integrity in the screen's shape."""
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("bs.pdf", make_native_pdf(), "application/pdf")}
    ).json()["id"]
    r = client.get(f"/api/v1/documents/{doc_id}/integrity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0 <= body["score"] <= 100
    assert body["grade"] and body["summary"]
    assert len(body["stats"]) == 4 and any(s["label"] == "Pages" for s in body["stats"])
    assert body["issues"]  # at least the "no issues" row for a clean native PDF
    assert all({"title", "detail", "pages", "note", "status", "severity"} <= set(i) for i in body["issues"])


def test_real_review_and_export_from_extraction(client):
    """A real uploaded file → extract → review queue + Excel/JSON export, all from the
    document's own run (no demo data)."""
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("bs.pdf", make_native_pdf(), "application/pdf")}
    ).json()["id"]
    client.post(f"/api/v1/documents/{doc_id}/extractions", json={})

    # Latest run is fetchable for the export preview/counts.
    run = client.get(f"/api/v1/documents/{doc_id}/run")
    assert run.status_code == 200 and run.json()["result"]["rows"]

    # Review queue derives from the real rows.
    rev = client.get(f"/api/v1/documents/{doc_id}/review").json()
    assert set(rev) == {"checks", "tabs", "summary"}
    assert rev["tabs"][0]["label"] == "All"
    assert rev["summary"]["open"] + rev["summary"]["passed"] >= 1

    # JSON export contains the real line items with source locations.
    j = client.get(f"/api/v1/documents/{doc_id}/export", params={"fmt": "json"})
    assert j.status_code == 200 and j.headers["content-type"].startswith("application/json")
    body = j.json()
    assert body["source_document"] == "bs.pdf" and body["line_item_count"] >= 1
    assert any("Trade receivables" in (li["source_label"] or "") for li in body["line_items"])

    # Excel export is a real workbook.
    x = client.get(f"/api/v1/documents/{doc_id}/export", params={"fmt": "excel"})
    assert x.status_code == 200
    assert x.content[:2] == b"PK" and len(x.content) > 200          # xlsx = zip


def test_review_and_run_404_before_extraction(client):
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("x.pdf", make_native_pdf(), "application/pdf")}
    ).json()["id"]
    # No run yet → /run and /export 404; /review returns an empty (but valid) queue.
    assert client.get(f"/api/v1/documents/{doc_id}/run").status_code == 404
    assert client.get(f"/api/v1/documents/{doc_id}/export", params={"fmt": "json"}).status_code == 404
    rev = client.get(f"/api/v1/documents/{doc_id}/review").json()
    assert rev["summary"] == {"open": 0, "passed": 0}


def test_missing_integrity_report_is_not_shown_as_clean(client):
    """A document with no stored integrity report must NOT be reported as a clean all-clear."""
    from app.api.routes.documents import _serialize_document_integrity

    class _Row:
        integrity_report = None
        page_count = 3
    body = _serialize_document_integrity(_Row())
    assert body["grade"] == "Not analyzed" and body["score"] == 0
    assert all(i["severity"] != "ok" for i in body["issues"])


def test_page_image_endpoint_renders_png(client):
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("bs.pdf", make_native_pdf(), "application/pdf")}
    ).json()["id"]
    r = client.get(f"/api/v1/documents/{doc_id}/pages/0/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n" and len(r.content) > 100


def test_reference_ontology_seeded_and_attached_run_maps(client):
    """The shipped HK ontology is seeded; attaching it to a run populates canonical keys
    (deterministic here — the alias tier maps offline without an LLM)."""
    from app.config import get_settings
    from app.services import settings_state  # noqa: F401 (import parity with other tests)

    onts = client.get("/api/v1/ontologies").json()
    ont = next(o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v1")
    tpls = client.get("/api/v1/templates").json()
    tpl = next(t for t in tpls if t["template_key"] == ont["target_template_key"])

    doc_id = client.post(
        "/api/v1/documents", files={"file": ("bs.pdf", make_native_pdf(), "application/pdf")}
    ).json()["id"]

    s = get_settings()
    prev = s.extraction.llm_mapping
    s.extraction.llm_mapping = False  # force the deterministic ensemble (no network) for the test
    try:
        r = client.post(f"/api/v1/documents/{doc_id}/extractions",
                        json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
        assert r.status_code == 202, r.text
        rows = r.json()["result"]["rows"]
        tr = next(row for row in rows if "Trade receivables" in row["source_label"])
        assert tr["canonical_key"], "expected the caption to map to a canonical concept"
    finally:
        s.extraction.llm_mapping = prev


def test_scanned_page_routes_through_ocr_port():
    """A scanned page is rasterized and sent to the configured OCR provider; its words
    (already normalized) reconstruct into line items with source_kind 'ocr'."""
    from app.config import get_settings
    from app.core.models.document import DocumentModel, PageSource
    from app.core.models.enums import DocFormat, PageKind, PageSourceKind
    from app.core.models.geometry import BBox
    from app.core.stage import PipelineContext
    from app.ports.registry import registry
    from app.services.pdf_extract import extract_pdf

    class _FakeOcr:
        id = "fakeocr"

        def recognize(self, image_bytes, *, lang="en"):
            return {"words": [
                {"text": "Cash", "bbox": BBox(x0=0.10, y0=0.20, x1=0.20, y1=0.23), "confidence": 0.99},
                {"text": "and", "bbox": BBox(x0=0.21, y0=0.20, x1=0.26, y1=0.23), "confidence": 0.99},
                {"text": "equivalents", "bbox": BBox(x0=0.27, y0=0.20, x1=0.40, y1=0.23), "confidence": 0.99},
                {"text": "1,204", "bbox": BBox(x0=0.80, y0=0.20, x1=0.90, y1=0.23), "confidence": 0.98},
            ], "angle": 0.0}

        def detect_orientation(self, image_bytes):
            return 0.0

    registry.register("ocr", "fakeocr", _FakeOcr)
    settings = get_settings()
    prev = settings.ocr.engine
    settings.ocr.engine = "fakeocr"
    try:
        doc = DocumentModel(filename="scan.pdf", content_hash="h1")
        doc.fmt = DocFormat.PDF
        doc.pages = [PageSource(index=0, source_kind=PageSourceKind.SCANNED, kind=PageKind.FACE)]
        ctx = PipelineContext(raw_bytes=make_native_pdf())
        added = extract_pdf(make_native_pdf(), doc, ctx)
        assert added >= 1
        item = doc.line_items[0]
        assert "Cash" in item.source_label
        ev = next(iter(item.values.values()))
        assert int(ev.value) == 1204
        assert ev.provenance.source_kind == "ocr" and ev.provenance.bbox is not None
    finally:
        settings.ocr.engine = prev

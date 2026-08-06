from __future__ import annotations

import pytest

from tests.fixtures.generate import make_native_pdf

pytest.importorskip("fitz")


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_upload_document_returns_integrity_and_pages(client):
    pdf_bytes = make_native_pdf()  # reuse identical bytes so dedup can trigger
    r = client.post("/api/v1/documents", files={"file": ("bs.pdf", pdf_bytes, "application/pdf")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["format"] == "pdf"
    assert body["page_count"] == 1
    assert body["integrity_report"] is not None
    assert body["locale"] == "en"

    # Re-upload the SAME bytes → dedup by content hash.
    r2 = client.post("/api/v1/documents", files={"file": ("bs.pdf", pdf_bytes, "application/pdf")})
    assert r2.json()["duplicate_of"] is not None


def test_template_and_ontology_create_and_language_parity(client):
    template = {
        "template_key": "api_tpl",
        "name": "API Template",
        "statements": [{
            "type": "balance_sheet",
            "sections": [{
                "node_id": "cash", "canonical_key": "cash", "label": "Cash", "role": "line",
                "label_i18n": {"en": "Cash", "zh": "现金", "ar": "النقد", "fr": "Trésorerie"},
            }],
        }],
    }
    admin = {"X-Role": "admin"}
    r = client.post("/api/v1/templates", json={"definition": template}, headers=admin)
    assert r.status_code == 201, r.text
    tpl_id = r.json()["id"]

    ontology = {
        "ontology_key": "api_ont",
        "target_template_key": "api_tpl",
        "number_format_by_locale": {loc: {} for loc in ("en", "zh", "ar", "fr")},
        "mappings": [{
            "canonical_key": "cash",
            "aliases_i18n": {"en": ["Cash"], "zh": ["现金"], "ar": ["النقد"], "fr": ["Trésorerie"]},
        }],
    }
    r = client.post("/api/v1/ontologies", json={"definition": ontology}, headers=admin)
    assert r.status_code == 201, r.text
    ont_id = r.json()["id"]

    r = client.get(f"/api/v1/languages?template_version_id={tpl_id}&ontology_version_id={ont_id}")
    assert r.status_code == 200
    body = r.json()
    assert set(body["fully_supported"]) == {"en", "zh", "ar", "fr"}


def test_ontology_rejects_unknown_template(client):
    ontology = {"ontology_key": "orphan", "target_template_key": "nope", "mappings": []}
    r = client.post("/api/v1/ontologies", json={"definition": ontology}, headers={"X-Role": "admin"})
    assert r.status_code == 422


def test_extraction_confirm_scope_defaults_to_auto(client):
    """confirm_scope defaults to False (auto mode) and round-trips when set."""
    pdf_bytes = make_native_pdf()
    doc_id = client.post(
        "/api/v1/documents", files={"file": ("bs.pdf", pdf_bytes, "application/pdf")}
    ).json()["id"]

    # Default: no confirm_scope in body → auto mode (False).
    r = client.post(f"/api/v1/documents/{doc_id}/extractions", json={})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    from app.db.base import SessionLocal
    from app.db.models import ExtractionRun

    with SessionLocal() as s:
        assert s.get(ExtractionRun, run_id).options["confirm_scope"] is False

    # Explicit confirm mode round-trips.
    r = client.post(
        f"/api/v1/documents/{doc_id}/extractions", json={"confirm_scope": True}
    )
    assert r.status_code == 202, r.text
    with SessionLocal() as s:
        assert s.get(ExtractionRun, r.json()["run_id"]).options["confirm_scope"] is True

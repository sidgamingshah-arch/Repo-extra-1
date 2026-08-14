"""The audit trail: reachable for a real document, and carrying how long each run took."""
from __future__ import annotations

import uuid


def _seed_document(session, owner: str = "analyst"):
    from app.db.models import Document

    row = Document(filename="audited.pdf", fmt="pdf", byte_size=1,
                   object_key=f"audit/{uuid.uuid4().hex}.pdf",
                   content_hash=f"audit-{uuid.uuid4().hex}", owner=owner)
    session.add(row)
    session.flush()
    return row.id


def test_a_run_recorded_against_a_document_is_readable_from_that_document(client, anon_client, auth):
    """THE GAP THIS CLOSES. Runs against an uploaded document have always been recorded under the
    DOCUMENT's id — extraction on both outcomes, and the credit narrative — and nothing served that
    key. The only audit route was the project's, the client asked it for the demo project, and so
    every real run wrote an entry into a bucket no screen could reach. An audit trail that is kept
    and cannot be read is not an audit trail.

    Asserted end to end through the API rather than against the store, because the defect was
    entirely in the reachability: `recorded()` had the entry all along.
    """
    from app.db.base import SessionLocal
    from app.db.models import Document
    from app.services import audit as audit_svc

    with SessionLocal() as s:
        doc_id = _seed_document(s)
        s.commit()
    audit_svc.record(doc_id, audit_svc.AuditEntry(
        run_id="acme-20260814-000001", entity="Acme Holdings Limited", action="extraction",
        provider="anthropic", model="claude-x", input_tokens=1200, output_tokens=340,
        status="succeeded", duration_ms=8_500))
    try:
        got = anon_client.get(f"/api/v1/documents/{doc_id}/audit", headers=auth("analyst"))
        assert got.status_code == 200, got.text
        entries = got.json()["entries"]
        assert [e["run_id"] for e in entries] == ["acme-20260814-000001"]
        e = entries[0]
        assert e["entity"] == "Acme Holdings Limited"
        assert e["total_tokens"] == 1540              # derived, never stored twice
        assert e["duration_ms"] == 8_500
        # The DEMO project's trail is a different key and must not have absorbed it — that conflation
        # is what the client was doing.
        demo = client.get("/api/v1/projects/demo/audit").json()["entries"]
        assert "acme-20260814-000001" not in [x["run_id"] for x in demo]
    finally:
        audit_svc.clear(doc_id)
        with SessionLocal() as s:
            s.delete(s.get(Document, doc_id))
            s.commit()


def test_another_owners_document_audit_is_not_found(anon_client, auth):
    """The trail names entities and token spend, so it is scoped like every other document read:
    404 (not 403) by the same predicate, because existence must not leak across tenants."""
    from app.db.base import SessionLocal
    from app.db.models import Document

    with SessionLocal() as s:
        doc_id = _seed_document(s, owner="someone-else")
        s.commit()
    try:
        got = anon_client.get(f"/api/v1/documents/{doc_id}/audit", headers=auth("analyst"))
        assert got.status_code == 404, got.text
    finally:
        with SessionLocal() as s:
            s.delete(s.get(Document, doc_id))
            s.commit()


def test_the_trail_is_newest_first_on_both_routes(client, anon_client, auth):
    """Ordering is the readability of a trail, and two routes serve one — so both go through
    ``served_trail`` rather than sorting separately and drifting apart."""
    from app.db.base import SessionLocal
    from app.db.models import Document
    from app.services import audit as audit_svc

    with SessionLocal() as s:
        doc_id = _seed_document(s)
        s.commit()
    for n, stamp in ((1, "2026-01-01T00:00:00+00:00"), (2, "2026-06-01T00:00:00+00:00")):
        audit_svc.record(doc_id, audit_svc.AuditEntry(
            run_id=f"r{n}", entity="E", action="extraction", provider="stub", model="m",
            input_tokens=None, output_tokens=None, created_at=stamp))
    try:
        entries = anon_client.get(f"/api/v1/documents/{doc_id}/audit",
                                  headers=auth("analyst")).json()["entries"]
        assert [e["run_id"] for e in entries] == ["r2", "r1"]
        project = client.get("/api/v1/projects/demo/audit").json()["entries"]
        stamps = [e.get("created_at", "") for e in project]
        assert stamps == sorted(stamps, reverse=True)
    finally:
        audit_svc.clear(doc_id)
        with SessionLocal() as s:
            s.delete(s.get(Document, doc_id))
            s.commit()


def test_an_instantaneous_event_reports_no_duration_rather_than_zero():
    """A submission handed to a reviewer is an instant, not an interval. None renders as "—";
    a 0 would render as a measured run that took no time, which is a different claim."""
    from app.services import audit as audit_svc

    e = audit_svc.AuditEntry(run_id="r", entity="E", action="submit_review", provider="—",
                             model="—", input_tokens=None, output_tokens=None)
    assert e.to_dict()["duration_ms"] is None


def test_elapsed_ms_is_never_negative():
    """One spelling of "how long did this take", and it refuses to report a negative interval: a
    clock that has gone backwards should say "no time at all", not render a nonsense figure."""
    from datetime import datetime, timedelta, timezone

    from app.services import audit as audit_svc

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert audit_svc.elapsed_ms(future) == 0
    past = datetime.now(timezone.utc) - timedelta(seconds=2)
    assert 1_800 <= audit_svc.elapsed_ms(past) <= 2_500


def test_a_naive_start_stamp_is_read_as_utc_rather_than_raising():
    """A stamp with no zone must not blow up the recording of a run's outcome.

    The extraction task rebuilds its start from an ISO string, which need not carry a zone, and
    subtracting naive from aware raises TypeError. Raised here it would fire while recording the
    outcome — on the FAILURE path too, abandoning the run row at "running" with a client polling it
    for ever. Caught by ``test_extraction_progress`` the first time, because that path already had a
    test; pinned here as well since the normalisation now lives in this function.
    """
    from datetime import datetime, timedelta

    from app.services import audit as audit_svc

    naive = datetime.utcnow() - timedelta(seconds=2)   # noqa: DTZ003 — a naive stamp is the point
    assert naive.tzinfo is None
    assert 1_800 <= audit_svc.elapsed_ms(naive) <= 2_500


def test_a_real_extraction_records_its_duration_on_the_documents_trail(client):
    """The whole thing, through the real pipeline: run an extraction and read its duration back off
    the document's own trail. This is the pair of gaps closed together — the entry is reachable, and
    it says how long the run took."""
    import pytest
    pytest.importorskip("reportlab")
    from tests.fixtures.generate import make_native_pdf

    data = make_native_pdf()
    up = client.post("/api/v1/documents", files={"file": ("dur.pdf", data, "application/pdf")})
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]
    started = client.post(f"/api/v1/documents/{doc_id}/extractions", json={})
    assert started.status_code == 202, started.text

    entries = client.get(f"/api/v1/documents/{doc_id}/audit").json()["entries"]
    extraction = [e for e in entries if e["action"] == "extraction"]
    assert extraction, entries
    e = extraction[0]
    assert e["duration_ms"] is not None and e["duration_ms"] >= 0
    assert e["status"] in ("succeeded", "failed")

"""The /languages endpoint, called with no template/ontology, defaults to the seeded config
so it reports a real fully-supported set rather than an all-False collapse (Req 21)."""
from __future__ import annotations


def test_languages_default_reports_supported_set(client):
    body = client.get("/api/v1/languages").json()
    assert body["languages"], "languages list should not be empty"
    # With the default falling back to the seeded template/ontology, English resolves as fully
    # supported instead of the previous all-False collapse; other locales honestly report the
    # specific artifacts they still lack (per the parity gate).
    assert "en" in body["fully_supported"]
    assert all({"locale", "supported", "missing"} <= set(l) for l in body["languages"])
    not_full = [l for l in body["languages"] if not l["supported"]]
    assert all(l["missing"] for l in not_full)   # a real reason, not a blanket false

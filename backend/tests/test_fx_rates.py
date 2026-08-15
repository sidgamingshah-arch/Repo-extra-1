"""FX rate master: CRUD, RBAC, validation, and honest resolution.

The master is admin-maintained with no feed behind it, so these tests pin the two things
that make a converted figure trustworthy: only an admin can change a rate, and resolution
either names the rate it used (flagging a reciprocal as derived) or admits it has none.
"""
from __future__ import annotations

BASE = "/api/v1/fx-rates"


def _clear(client):
    """Drop every stored rate — the master is process-wide, so tests must not inherit rows."""
    for r in client.get(BASE).json()["rates"]:
        client.delete(f"{BASE}/{r['id']}")


def test_crud_happy_path(client):
    _clear(client)
    created = client.post(BASE, json={"base": "usd", "quote": "inr", "rate": "83.25",
                                      "as_of": "2026-08-01", "source": "Treasury desk"})
    assert created.status_code == 201, created.text
    row = created.json()
    # Codes are normalized on the way in so USD/usd cannot become two competing pairs.
    assert row["base"] == "USD" and row["quote"] == "INR"
    assert row["rate"] == "83.25" and row["as_of"] == "2026-08-01"
    assert row["source"] == "Treasury desk"
    assert row["created_at"] and row["updated_at"]

    listed = client.get(BASE).json()["rates"]
    assert [r["id"] for r in listed] == [row["id"]]

    updated = client.put(f"{BASE}/{row['id']}", json={"base": "USD", "quote": "INR",
                                                      "rate": "83.9", "as_of": "2026-08-02"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["rate"] == "83.9" and updated.json()["as_of"] == "2026-08-02"

    assert client.delete(f"{BASE}/{row['id']}").status_code == 204
    assert client.get(BASE).json()["rates"] == []
    # Deleting/updating something that is gone is a 404, not a silent success.
    assert client.delete(f"{BASE}/{row['id']}").status_code == 404
    assert client.put(f"{BASE}/{row['id']}", json={"base": "USD", "quote": "INR",
                                                   "rate": "1"}).status_code == 404


def test_post_restates_same_pair_and_date(client):
    """A second POST for the same pair + as-of corrects the rate instead of adding a rival row."""
    _clear(client)
    first = client.post(BASE, json={"base": "EUR", "quote": "USD", "rate": "1.08",
                                    "as_of": "2026-08-01"})
    second = client.post(BASE, json={"base": "EUR", "quote": "USD", "rate": "1.09",
                                     "as_of": "2026-08-01", "source": "ECB"})
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    rates = client.get(BASE).json()["rates"]
    assert len(rates) == 1 and rates[0]["rate"] == "1.09" and rates[0]["source"] == "ECB"


def test_as_of_defaults_to_today(client):
    """Every rate carries a real date — a caption without one can't show staleness."""
    from datetime import datetime, timezone

    _clear(client)
    r = client.post(BASE, json={"base": "GBP", "quote": "USD", "rate": "1.27"})
    assert r.status_code == 201, r.text
    assert r.json()["as_of"] == datetime.now(timezone.utc).date().isoformat()


def test_write_requires_admin_read_does_not(auth, anon_client):
    _clear_headers = auth("admin")
    for r in anon_client.get(BASE, headers=_clear_headers).json()["rates"]:
        anon_client.delete(f"{BASE}/{r['id']}", headers=_clear_headers)

    body = {"base": "USD", "quote": "SGD", "rate": "1.34", "as_of": "2026-08-01"}
    # Unauthenticated: no reading and no writing.
    assert anon_client.get(BASE).status_code == 401
    assert anon_client.post(BASE, json=body).status_code == 401
    # Working roles may read the master (the Workspace needs the rate) but not change it.
    for role in ("analyst", "reviewer"):
        assert anon_client.get(BASE, headers=auth(role)).status_code == 200
        assert anon_client.post(BASE, json=body, headers=auth(role)).status_code == 403
    created = anon_client.post(BASE, json=body, headers=_clear_headers)
    assert created.status_code == 201, created.text

    rate_id = created.json()["id"]
    assert anon_client.put(f"{BASE}/{rate_id}", json=body,
                           headers=auth("analyst")).status_code == 403
    assert anon_client.delete(f"{BASE}/{rate_id}", headers=auth("reviewer")).status_code == 403
    assert anon_client.delete(f"{BASE}/{rate_id}", headers=_clear_headers).status_code == 204


def test_resolve_requires_authentication(anon_client):
    assert anon_client.get(f"{BASE}/resolve?base=USD&quote=INR").status_code == 401


def test_validation_rejections(client):
    _clear(client)
    cases = [
        # A non-positive multiplier would zero out or sign-flip every converted figure.
        {"base": "USD", "quote": "INR", "rate": "0"},
        {"base": "USD", "quote": "INR", "rate": "-4"},
        {"base": "USD", "quote": "INR", "rate": "not-a-number"},
        # A self-pair is not a rate.
        {"base": "USD", "quote": "USD", "rate": "1"},
        # Codes must be ISO-4217 shaped.
        {"base": "US", "quote": "INR", "rate": "83"},
        {"base": "USD", "quote": "RUPEE", "rate": "83"},
        {"base": "", "quote": "INR", "rate": "83"},
    ]
    for body in cases:
        r = client.post(BASE, json=body)
        assert r.status_code == 422, (body, r.status_code, r.text)
        assert r.json()["detail"], body
    assert client.get(BASE).json()["rates"] == []
    # The same rules apply to an edit, not just a create.
    ok = client.post(BASE, json={"base": "USD", "quote": "INR", "rate": "83"})
    assert client.put(f"{BASE}/{ok.json()['id']}",
                      json={"base": "USD", "quote": "INR", "rate": "0"}).status_code == 422
    _clear(client)


def test_resolve_rejects_bad_pair(client):
    assert client.get(f"{BASE}/resolve?base=USD&quote=USD").status_code == 422
    assert client.get(f"{BASE}/resolve?base=usdollar&quote=INR").status_code == 422


def test_resolve_direct_is_not_derived(client):
    _clear(client)
    client.post(BASE, json={"base": "USD", "quote": "INR", "rate": "83.25",
                            "as_of": "2026-08-01", "source": "ECB"})
    r = client.get(f"{BASE}/resolve?base=USD&quote=INR")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resolved"] is True
    assert body["rate"] == "83.25" and body["as_of"] == "2026-08-01"
    assert body["derived"] is False and body["method"] == "direct"
    assert body["path"] == ["USD", "INR"] and body["source"] == "ECB"
    _clear(client)


def test_resolve_uses_newest_as_of(client):
    """Restating a pair on a later date supersedes the older quote."""
    _clear(client)
    client.post(BASE, json={"base": "USD", "quote": "INR", "rate": "83.00",
                            "as_of": "2026-08-01"})
    client.post(BASE, json={"base": "USD", "quote": "INR", "rate": "84.10",
                            "as_of": "2026-08-05"})
    body = client.get(f"{BASE}/resolve?base=USD&quote=INR").json()
    # Stored in canonical form, so the trailing zero of "84.10" is dropped.
    assert body["rate"] == "84.1" and body["as_of"] == "2026-08-05"
    _clear(client)


def test_resolve_inverse_is_labelled_derived(client):
    """Only USD->INR is held, so INR->USD comes back as OUR reciprocal, flagged as such."""
    _clear(client)
    client.post(BASE, json={"base": "USD", "quote": "INR", "rate": "80",
                            "as_of": "2026-08-01", "source": "ECB"})
    body = client.get(f"{BASE}/resolve?base=INR&quote=USD").json()
    assert body["resolved"] is True
    assert body["derived"] is True and body["method"] == "inverse"
    # The path names the stored direction that was inverted, not a pair we hold.
    assert body["path"] == ["USD", "INR"]
    assert body["rate"] == "0.0125"
    assert body["as_of"] == "2026-08-01"
    _clear(client)


def test_resolve_inverse_keeps_decimal_precision(client):
    """1/83.25 has no finite decimal form; the reciprocal must still round-trip closely."""
    from decimal import Decimal

    _clear(client)
    client.post(BASE, json={"base": "USD", "quote": "INR", "rate": "83.25",
                            "as_of": "2026-08-01"})
    rate = Decimal(client.get(f"{BASE}/resolve?base=INR&quote=USD").json()["rate"])
    assert abs(rate * Decimal("83.25") - 1) < Decimal("1e-18")
    _clear(client)


def test_resolve_reports_no_rate_instead_of_inventing_one(client):
    """An empty/incomplete master answers 200 with resolved=false — never a fallback of 1,
    which would show source figures under a target-currency label."""
    _clear(client)
    body = client.get(f"{BASE}/resolve?base=JPY&quote=CAD").json()
    assert body["resolved"] is False
    assert body["reason"] == "no_rate_configured"
    assert "JPY" in body["detail"] and "CAD" in body["detail"]
    assert "rate" not in body


def test_no_triangulation_through_a_third_currency(client):
    """USD->EUR and EUR->GBP exist, but GBP is not quoted against USD: chaining two
    independently-dated rates would manufacture a quote nobody published."""
    _clear(client)
    client.post(BASE, json={"base": "USD", "quote": "EUR", "rate": "0.92",
                            "as_of": "2026-08-01"})
    client.post(BASE, json={"base": "EUR", "quote": "GBP", "rate": "0.85",
                            "as_of": "2026-07-01"})
    body = client.get(f"{BASE}/resolve?base=USD&quote=GBP").json()
    assert body["resolved"] is False and body["reason"] == "no_rate_configured"
    _clear(client)


def test_master_is_empty_by_default(client, auth, anon_client):
    """Nothing is seeded: with no admin input the master holds no rates at all."""
    _clear(client)
    assert client.get(BASE).json()["rates"] == []
    assert anon_client.get(BASE, headers=auth("analyst")).json()["rates"] == []

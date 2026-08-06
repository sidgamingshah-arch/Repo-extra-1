from __future__ import annotations

from decimal import Decimal

from app.sample.demo import BALANCE_SHEET
from app.services import checks as ce


def test_project_and_statement(client):
    r = client.get("/api/v1/projects/demo")
    assert r.status_code == 200
    assert r.json()["project"]["entity"] == "Reliance Industries Ltd"

    r = client.get("/api/v1/projects/demo/statements/balance_sheet?basis=consolidated")
    body = r.json()
    ppe = next(x for x in body["rows"] if x["id"] == "ppe")
    assert ppe["v1"] == 423180
    assert ppe["confidence"]["pct"] == 96
    assert ppe["note"] == "3"


def test_localized_statement_labels(client):
    # Chinese output labels; source_label stays English (input→output parity).
    zh = client.get("/api/v1/projects/demo/statements/balance_sheet?locale=zh").json()
    ppe = next(x for x in zh["rows"] if x["id"] == "ppe")
    assert ppe["label"] == "物业、厂房及设备"
    assert ppe["source_label"] == "Property, plant and equipment"
    assert zh["label"] == "资产负债表"  # statement name localized too

    # Arabic + French resolve; unknown locale falls back to English.
    ar = client.get("/api/v1/projects/demo/statements/balance_sheet?locale=ar").json()
    assert next(x for x in ar["rows"] if x["id"] == "tot_assets")["label"] == "إجمالي الأصول"
    fr = client.get("/api/v1/projects/demo/statements/balance_sheet?locale=fr").json()
    assert next(x for x in fr["rows"] if x["id"] == "trade_recv")["label"] == "Créances clients"
    en = client.get("/api/v1/projects/demo/statements/balance_sheet?locale=en").json()
    assert next(x for x in en["rows"] if x["id"] == "ppe")["label"] == "Property, plant and equipment"


def test_standalone_scaling():
    from app.api.routes.projects import _scale
    assert _scale(423180, "standalone") == round(423180 * 0.88)
    assert _scale(423180, "consolidated") == 423180


def test_edit_override_roundtrip(client):
    r = client.patch("/api/v1/projects/demo/line-items/ppe",
                     json={"value": 430000, "formula": "Note3.net_block + 6820"})
    assert r.status_code == 200
    body = client.get("/api/v1/projects/demo/statements/balance_sheet").json()
    ppe = next(x for x in body["rows"] if x["id"] == "ppe")
    assert ppe["v1"] == 430000
    assert ppe["status"] == "edited"
    assert ppe["formula"] == "Note3.net_block + 6820"
    # revert
    client.delete("/api/v1/projects/demo/line-items/ppe")
    body = client.get("/api/v1/projects/demo/statements/balance_sheet").json()
    ppe = next(x for x in body["rows"] if x["id"] == "ppe")
    assert ppe["v1"] == 423180


def test_localized_dynamic_content(client):
    # Review checks, integrity issues, and note detail localize with ?locale.
    zh_review = client.get("/api/v1/projects/demo/review?locale=zh").json()
    assert zh_review["checks"][0]["title"] == "资产负债表不平衡"
    fr_integ = client.get("/api/v1/projects/demo/integrity?locale=fr").json()
    assert any(i["title"] == "Pages pivotées" for i in fr_integ["issues"])
    ar_note = client.get("/api/v1/projects/demo/notes/12?locale=ar").json()
    assert ar_note["reconciliation"] and "الإيضاح" in ar_note["reconciliation"]


def test_review_notes_endpoints(client):
    review = client.get("/api/v1/projects/demo/review").json()
    assert len(review["checks"]) == 4
    assert review["summary"]["open"] == 12

    note = client.get("/api/v1/projects/demo/notes/12").json()
    assert note["title"] == "Trade Receivables"
    assert note["linked_line"] == "trade_recv"


def test_export_xlsx_and_json(client):
    r = client.post("/api/v1/projects/demo/export", json={"format": "json"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert b"Trade receivables" in r.content

    r = client.post("/api/v1/projects/demo/export", json={"format": "excel"})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # xlsx is a zip container


# --- generic checks engine (used for real extractions) ---

def test_balance_check_passes_on_balanced_sheet():
    rows = [{"id": r["id"], "label": r["label"], "kind": r.get("kind", "item"),
             "v1": r.get("v1"), "v2": r.get("v2")} for r in BALANCE_SHEET]
    results = ce.check_balance(rows)
    assert results and results[0].status == "pass"
    assert results[0].delta == Decimal(0)


def test_balance_check_fails_on_imbalance():
    rows = [{"id": "tot_assets", "kind": "total", "v1": 1268100},
            {"id": "tot_eq", "kind": "total", "v1": 1266860}]
    r = ce.check_balance(rows)[0]
    assert r.status == "fail" and r.delta == Decimal(1240)


def test_subtotal_rollup_detects_mismatch():
    rows = [
        {"id": "sh", "kind": "subhead", "label": "X"},
        {"id": "a", "kind": "item", "label": "a", "v1": 100},
        {"id": "b", "kind": "item", "label": "b", "v1": 200},
        {"id": "sub", "kind": "subtotal", "label": "Sub", "v1": 310},  # should be 300
    ]
    checks = ce.check_subtotals(rows)
    assert checks[0].status == "fail" and checks[0].delta == Decimal(10)


def test_sign_anomaly_flags_positive_expense():
    rows = [{"id": "fin", "kind": "item", "label": "Finance costs", "v1": 18400}]
    checks = ce.check_signs(rows)
    assert checks and checks[0].type == "sign" and checks[0].target == "fin"

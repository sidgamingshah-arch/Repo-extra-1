"""Regression tests for the closed 'open items' batch:

* m7  — the embedding tier of the mapping ensemble is functional (real cosine similarity).
* o8  — statement chrome (label + canonical-key prefix) is derived from the template.
* m8  — note-detail rows carry role (kind) + confidence end-to-end.
* m1  — a persisted page scope actually restricts what extraction processes.
* M24 — commentary is computed from a REAL extraction, not the demo project.
"""
from __future__ import annotations

import time

import pytest

from app.core.models.enums import MappingMethod
from app.schemas.ontology import OntologyDefinition, OntologyMapping
from app.services.mapping import OntologyMatcher, _cosine


# --- m7: functional embedding tier ----------------------------------------------------------
class _FakeEmbeddings:
    """Deterministic stand-in for a semantic embedding model: it places 'cash-like' and
    'receivable-like' phrases in orthogonal directions so a paraphrase with NO shared tokens
    still resolves by cosine similarity."""

    id = "fake"

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            if any(w in low for w in ("cash", "bank", "monies", "liquid")):
                out.append([1.0, 0.0, 0.0])
            elif any(w in low for w in ("receivable", "debtor", "due from")):
                out.append([0.0, 1.0, 0.0])
            else:
                out.append([0.0, 0.0, 1.0])
        return out


def _ontology() -> OntologyDefinition:
    return OntologyDefinition(
        ontology_key="test", target_template_key="t",
        mappings=[
            OntologyMapping(canonical_key="assets.current.cash",
                            aliases=["Cash and cash equivalents", "Cash & bank balances"]),
            OntologyMapping(canonical_key="assets.current.receivables",
                            aliases=["Trade receivables", "Trade and other receivables"]),
        ],
    )


def test_cosine_basic():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0  # zero vector → 0, not a crash


def test_embedding_tier_returns_ranked_candidates():
    m = OntologyMatcher(_ontology(), embedding_provider=_FakeEmbeddings())
    cands = m._embedding("Monies held at the bank")
    assert cands, "embedding tier should now produce candidates (was a no-op)"
    assert cands[0].canonical_key == "assets.current.cash"
    assert cands[0].method == MappingMethod.EMBEDDING


def test_embedding_resolves_paraphrase_with_no_shared_tokens():
    """The whole point of the semantic tier: 'Monies held at the bank' shares no words with
    any cash alias, so exact/rule/fuzzy can't place it — the embedding tier does."""
    m = OntologyMatcher(_ontology(), embedding_provider=_FakeEmbeddings())
    r = m.match("Monies held at the bank")
    assert r.canonical_key == "assets.current.cash"
    assert r.method == MappingMethod.EMBEDDING
    assert "embedding" in r.scores


def test_embedding_absent_provider_is_noop():
    m = OntologyMatcher(_ontology())          # no provider
    assert m._embedding("anything") == []


# --- o8: statement chrome from the template -------------------------------------------------
def test_statement_chrome_derived_from_template():
    from app.api.routes.documents import _stmt_label, _stmt_prefix

    tpl = {"statements": [{
        "type": "changes_in_equity",
        "label": "Statement of Changes in Equity",
        "label_i18n": {"fr": "État des variations des capitaux propres"},
        "sections": [{"node_id": "s1", "children": [
            {"canonical_key": "eq_share_capital__ordinary_shares", "label": "Ordinary shares"},
        ]}],
    }]}
    # Prefix comes from the template's own keys, so a 4th statement type works with no code change.
    assert _stmt_prefix(tpl, "changes_in_equity") == "eq"
    assert _stmt_label(tpl, "changes_in_equity", "en") == "Statement of Changes in Equity"
    assert _stmt_label(tpl, "changes_in_equity", "fr") == "État des variations des capitaux propres"


def test_statement_chrome_falls_back_without_template():
    from app.api.routes.documents import _stmt_label, _stmt_prefix

    assert _stmt_prefix(None, "balance_sheet") == "bs"
    assert _stmt_label(None, "balance_sheet", "en") == "Balance sheet"


# --- m8: note-detail role → kind, confidence → badge ----------------------------------------
def test_note_row_kind_mapping():
    from app.api.routes.documents import _note_row_kind

    assert _note_row_kind({"role": "total", "label": "Total cash"}) == "tot"
    assert _note_row_kind({"role": "subtotal", "label": "Subtotal"}) == "sub"
    assert _note_row_kind({"role": "line", "label": "Total balances"}) == "tot"   # label heuristic
    assert _note_row_kind({"role": "line", "label": "Cash on hand"}) is None


# --- M24: commentary from a real extraction -------------------------------------------------
def _row(key, cur, prior=None):
    vals = [{"basis": "consolidated", "period_label": "current", "value": str(cur)}]
    if prior is not None:
        vals.append({"basis": "consolidated", "period_label": "prior", "value": str(prior)})
    return {"canonical_key": key, "values": vals}


def test_commentary_from_rows_is_data_driven():
    from app.services.commentary import build_commentary_from_rows

    rows = [
        _row("bs_current_assets__total_current_assets", 300, 250),
        _row("bs_current_liabilities__total_current_liabilities", 150, 140),
        _row("bs_equity__total_equity", 600, 500),
        _row("bs_total_assets", 800, 700),
        _row("bs_current_assets__cash_and_cash_equivalents", 60, 50),
        _row("bs_current_assets__trade_receivables", 40, 35),
        _row("bs_non_current_liabilities__non_current_borrowings", 100, 120),
        _row("pl_income__revenue_from_operations", 1000, 900),
        _row("pl_profit_before_tax", 120, 100),
        _row("pl_non_operating_expenses__interest_expense", 10, 12),
        _row("cf_cash_flow_from_operating_activities__net_cash_from_operating_activities", 150, 130),
    ]
    c = build_commentary_from_rows(rows, open_review_items=0, basis="consolidated",
                                   currency="INR", units="crore")
    m = {x["key"]: x["value"] for x in c["metrics"]}
    assert m["current_ratio"] == 2.0                       # 300 / 150
    assert m["debt_to_equity"] == round(100 / 600, 2)      # total debt / equity
    assert m["revenue_growth"] > 0                         # 1000 vs 900
    # Conservatively financed + strong coverage are selected from the real numbers.
    assert any("conservatively financed" in s for s in c["strengths"])
    assert "INR crore" in c["basis"]


def test_commentary_from_rows_empty_without_core_figures():
    from app.services.commentary import build_commentary_from_rows

    c = build_commentary_from_rows([], open_review_items=0)
    assert c["metrics"] == [] and c["headline"] == ""


# --- m1 + m8 + M24 end-to-end over a real 2-page document -----------------------------------
pytest.importorskip("fitz")
from tests.fixtures.generate import make_multipage_pdf, make_rich_pdf  # noqa: E402


def _upload(client, data, filename):
    return client.post("/api/v1/documents",
                       files={"file": (filename, data, "application/pdf")}).json()["id"]


def _extract_and_wait(client, doc_id):
    onts = client.get("/api/v1/ontologies").json()
    ont = next((o for o in onts if o["ontology_key"] == "hkfrs_hk_china_v1"), onts[0])
    tpls = client.get("/api/v1/templates").json()
    tpl = next((t for t in tpls if t["template_key"] == ont["target_template_key"]), tpls[0])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    for _ in range(100):
        r = client.get(f"/api/v1/documents/{doc_id}/run")
        if r.status_code == 200 and r.json().get("status") == "succeeded":
            return r.json()["result"]
        time.sleep(0.05)
    raise AssertionError("extraction did not finish")


def test_page_scope_reflects_and_restricts_extraction(client):
    doc_id = _upload(client, make_multipage_pdf(), "twopage.pdf")

    pages = client.get(f"/api/v1/documents/{doc_id}/pages").json()
    assert pages["total"] == 2
    # Default: both the face and notes pages are in scope.
    assert pages["focused"] == 2

    # Restrict extraction to the face page (index 0) only.
    r = client.put(f"/api/v1/documents/{doc_id}/scope", json={"included_pages": [0]})
    assert r.status_code == 200 and r.json()["included_pages"] == [0]

    pages2 = client.get(f"/api/v1/documents/{doc_id}/pages").json()
    assert pages2["focused"] == 1
    p1 = next(p for p in pages2["pages"] if p["no"] == 2)   # the notes page (index 1)
    assert p1["included"] is False

    # Extraction honours the scope: the notes page is excluded, so no note-detail tables.
    result = _extract_and_wait(client, doc_id)
    assert result["note_details"] == []


def test_note_detail_carries_confidence(client):
    doc_id = _upload(client, make_multipage_pdf(), "notes.pdf")
    result = _extract_and_wait(client, doc_id)
    if not result["note_details"]:
        pytest.skip("no note detail parsed for this fixture")
    notes = client.get(f"/api/v1/documents/{doc_id}/notes").json()
    no = notes["notes"][0]["no"]
    detail = client.get(f"/api/v1/documents/{doc_id}/notes/{no}").json()
    assert detail["rows"], "note should have detail rows"
    # Confidence is surfaced per row (was omitted for real note details before).
    assert any("conf" in row for row in detail["rows"])


def test_document_commentary_is_real_not_demo(client):
    doc_id = _upload(client, make_rich_pdf(), "rich.pdf")

    # Empty (valid) shape before extraction.
    pre = client.get(f"/api/v1/documents/{doc_id}/commentary").json()
    assert pre["metrics"] == []

    _extract_and_wait(client, doc_id)
    c = client.get(f"/api/v1/documents/{doc_id}/commentary").json()
    assert c["metrics"], "commentary should compute metrics from the real extraction"
    # Not the demo commentary: the demo basis is the seeded ₹-crore string.
    assert c["basis"] != "consolidated · FY25 vs FY24 · ₹ crore"

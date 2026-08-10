"""Face-line containment netting: a line stated inclusive of others is shown net of them, with
the formula surfaced. Deterministic and signed (works whether expenses are negative or positive)."""
from __future__ import annotations


def _row(key, label, cur, prior=None, basis="consolidated"):
    vals = [{"basis": basis, "period_label": "current", "value": str(cur)}]
    if prior is not None:
        vals.append({"basis": basis, "period_label": "prior", "value": str(prior)})
    return {"canonical_key": key, "source_label": label, "values": vals}


def test_compute_netting_signed_and_formula():
    from app.schemas.ontology import NettingRule
    from app.services.netting import compute_netting

    # Expenses stored as negatives (the usual convention). Cost of sales is stated inclusive of
    # admin and selling/marketing, so the clean figure adds those back (subtracting a negative).
    rows = [
        _row("pl_cost_of_sales", "Cost of sales", -18330, -16000),
        _row("pl_administrative_expenses", "Administrative expenses", -1710, -1500),
        _row("pl_selling_and_marketing", "Selling and marketing expenses", -802, -700),
    ]
    rule = NettingRule(id="cos_net", target_key="pl_cost_of_sales",
                       subtract_keys=["pl_administrative_expenses", "pl_selling_and_marketing"],
                       label="Cost of sales is stated inclusive of admin and S&M.")
    cur = compute_netting(rows, [rule], basis="consolidated", period="current")
    assert "pl_cost_of_sales" in cur
    info = cur["pl_cost_of_sales"]
    assert info["raw"] == "-18330"
    assert info["net"] == "-15818"          # -18330 − (−1710) − (−802)
    assert "Cost of sales" in info["formula"] and "−" in info["formula"]
    prior = compute_netting(rows, [rule], basis="consolidated", period="prior")
    assert prior["pl_cost_of_sales"]["net"] == "-13800"   # -16000 + 1500 + 700

    # Positive-expense convention nets the same way (straight subtraction).
    rows_pos = [
        _row("pl_cost_of_sales", "Cost of sales", 18330),
        _row("pl_administrative_expenses", "Administrative expenses", 1710),
    ]
    r2 = NettingRule(id="c2", target_key="pl_cost_of_sales",
                     subtract_keys=["pl_administrative_expenses"])
    assert compute_netting(rows_pos, [r2])["pl_cost_of_sales"]["net"] == "16620"


def test_compute_netting_noops_without_components():
    from app.schemas.ontology import NettingRule
    from app.services.netting import compute_netting

    rows = [_row("pl_cost_of_sales", "Cost of sales", -18330)]
    rule = NettingRule(id="x", target_key="pl_cost_of_sales",
                       subtract_keys=["pl_administrative_expenses"])  # not present in the doc
    assert compute_netting(rows, [rule]) == {}   # nothing to net → silently no-op


def test_statement_applies_netting_with_formula():
    """The Workspace statement shows the netted value on the target row and carries the formula
    (non-destructive: the raw figure is retained in the inspector note)."""
    from app.api.routes.documents import _build_statement
    from app.schemas.ontology import NettingRule

    rows = [
        _row("pl_income__revenue_from_operations", "Revenue", 45230),
        _row("pl_cost_of_sales", "Cost of sales", -18330),
        _row("pl_administrative_expenses", "Administrative expenses", -1710),
    ]
    # Minimal template placing the two lines on the P&L so they render as item rows.
    tpl = {"statements": [{"type": "profit_and_loss", "sections": [{"node_id": "s", "label": "P&L",
            "children": [
                {"canonical_key": "pl_cost_of_sales", "label": "Cost of sales"},
                {"canonical_key": "pl_administrative_expenses", "label": "Administrative expenses"},
            ]}]}]}
    rule = NettingRule(id="cos", target_key="pl_cost_of_sales",
                       subtract_keys=["pl_administrative_expenses"],
                       label="Inclusive of admin.")
    st = _build_statement(rows, tpl, "profit_and_loss", "doc.pdf", netting_rules=[rule])
    cos = next(r for r in st["rows"] if r.get("id") == "pl_cost_of_sales")
    assert cos["v1"] == -16620            # -18330 − (−1710)
    assert cos["formula"] and "Cost of sales" in cos["formula"]
    assert "Raw" in cos["inspector"]["note"]

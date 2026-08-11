"""Structural validation (template rollups + declared identities) catches mis-mapped values
arithmetically, stays silent when a relation's components weren't all extracted, and routes its
failures to the review queue."""
from __future__ import annotations

from decimal import Decimal

from app.core.models.enums import Basis
from app.core.models.line_item import ExtractedValue, LineItem
from app.schemas.loader import load_template
from app.services.structural_checks import evaluate_structure


def _node(node_id: str, role: str = "line", rollup: list[str] | None = None,
          op: str = "sum") -> dict:
    n = {"node_id": node_id, "canonical_key": node_id, "label": node_id, "role": role}
    if rollup is not None:
        n["rollup"] = {"op": op, "children": rollup}
    return n


def _pl_template(op: str = "sum", identities: list[dict] | None = None) -> dict:
    """Revenue + cost of sales → gross profit, as a template a filing could be spread onto."""
    return {
        "template_key": "t", "name": "t",
        "statements": [{
            "type": "profit_and_loss",
            "sections": [{
                "node_id": "s1", "canonical_key": "s1", "label": "Income", "role": "header",
                "children": [
                    _node("revenue"), _node("cost_of_sales"), _node("other_income"),
                    _node("gross_profit", "subtotal", ["revenue", "cost_of_sales"], op),
                ],
            }],
            "identities": identities or [],
        }],
    }


def _items(**by_key: object) -> list[LineItem]:
    """One line item per canonical key; a value may be a number or {period: number}."""
    out = []
    for key, val in by_key.items():
        li = LineItem(source_label=key, canonical_key=key)
        periods = val if isinstance(val, dict) else {"current": val}
        for period, num in periods.items():
            li.set_value(ExtractedValue(value=Decimal(str(num)), value_raw=Decimal(str(num)),
                                        basis=Basis.CONSOLIDATED, period_label=period))
        out.append(li)
    return out


def _one(report, rule_id: str, status: str | None = None):
    return next(r for r in report.results
                if r.rule_id == rule_id and (status is None or r.status == status))


def test_subtotal_that_adds_up_passes():
    tpl = load_template(_pl_template())
    report = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600, gross_profit=400))

    res = _one(report, "rollup:gross_profit")
    assert res.status == "pass" and res.difference == 0
    assert res.expected == 400 and res.actual == 400
    assert res.scope_key == "consolidated/current"
    assert report.failed_assertions == []


def test_subtotal_off_by_more_than_tolerance_fails_with_the_arithmetic():
    """A value mapped to the wrong concept shows up as a subtotal that doesn't add up — the
    finding carries the relation, both figures, the difference, the period and the keys."""
    tpl = load_template(_pl_template())
    report = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600, gross_profit=470))

    res = _one(report, "rollup:gross_profit")
    assert res.status == "fail" and res.kind == "rollup"
    assert (res.expected, res.actual, res.difference) == (400, 470, 70)
    assert res.details["target"] == "gross_profit"
    assert res.details["components"] == ["revenue", "cost_of_sales"]
    assert res.details["basis"] == "consolidated" and res.details["period_label"] == "current"
    assert res.details["component_values"] == {"revenue": "1000", "cost_of_sales": "-600"}
    assert report.failed_assertions and "gross_profit" in report.failed_assertions[0]


def test_missing_child_is_not_evaluable_rather_than_a_mismatch():
    """The template lists every line the framework allows, so an unextracted child must never
    read as a mismatch — that would fail nearly every subtotal on a partial extraction."""
    tpl = load_template(_pl_template())
    report = evaluate_structure(tpl, _items(revenue=1000, gross_profit=400))

    assert report.failures() == []
    res = _one(report, "rollup:gross_profit")
    assert res.status == "skipped"
    assert res.details["reason"] == "components_not_mapped"
    assert res.details["missing"] == ["cost_of_sales"]
    # No value is invented to close the gap.
    assert res.expected is None and res.actual is None


def test_total_or_components_absent_entirely_is_reported_as_coverage_not_failure():
    tpl = load_template(_pl_template())
    report = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600))

    res = _one(report, "rollup:gross_profit")
    assert res.status == "skipped" and res.details["reason"] == "target_not_extracted"
    assert not report.evaluated()


def test_expenses_stored_negative_or_positive_both_read_correctly():
    """Sums are signed: a cost printed in parentheses arrives negative and simply adds. The same
    figure stored positive breaks the relation, and the sign is named as the suspect."""
    tpl = load_template(_pl_template())

    signed = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600, gross_profit=400))
    assert _one(signed, "rollup:gross_profit").status == "pass"

    flipped = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=600, gross_profit=400))
    res = _one(flipped, "rollup:gross_profit")
    assert res.status == "fail" and res.difference == -1200
    assert res.details["sign_suspect"] == "cost_of_sales"


def test_sign_suspect_is_only_named_when_it_is_unambiguous():
    tpl = load_template(_pl_template())
    # Two equal-magnitude components: either flip would balance it, so neither is accused.
    report = evaluate_structure(tpl, _items(revenue=500, cost_of_sales=500, gross_profit=0))
    res = _one(report, "rollup:gross_profit")
    assert res.status == "fail" and res.details["sign_suspect"] is None


def test_tolerance_is_absolute_and_relative():
    tpl = load_template(_pl_template())

    # Absolute floor of 1 for small figures: exactly on the edge passes, a hair over fails.
    assert _one(evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600,
                                               gross_profit=401)),
                "rollup:gross_profit").status == "pass"
    assert _one(evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600,
                                               gross_profit="401.01")),
                "rollup:gross_profit").status == "fail"
    # Relative band (0.1%) on large figures — rounding in the filing isn't a defect.
    big = _items(revenue=20_000_000, cost_of_sales=-18_000_000, gross_profit=2_001_000)
    assert _one(evaluate_structure(tpl, big), "rollup:gross_profit").status == "pass"
    worse = _items(revenue=20_000_000, cost_of_sales=-18_000_000, gross_profit=2_010_000)
    assert _one(evaluate_structure(tpl, worse), "rollup:gross_profit").status == "fail"


def test_each_period_is_checked_on_its_own():
    tpl = load_template(_pl_template())
    report = evaluate_structure(tpl, _items(
        revenue={"current": 1000, "prior": 900},
        cost_of_sales={"current": -600, "prior": -500},
        gross_profit={"current": 400, "prior": 300}))

    results = {r.scope_key: r.status for r in report.evaluated()}
    assert results == {"consolidated/current": "pass", "consolidated/prior": "fail"}


def test_declared_identity_is_evaluated_from_the_template():
    """Identities come from the template's own ``identities``, with their own tolerance."""
    tpl = load_template(_pl_template(identities=[{
        "id": "gp_ties", "lhs": "gross_profit",
        "rhs": {"op": "diff", "children": ["revenue", "other_income"]},
        "tolerance_abs": 5.0, "tolerance_rel": 0.0,
    }]))
    report = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600, gross_profit=996,
                                            other_income=6))

    res = _one(report, "identity:gp_ties")
    assert res.kind == "identity" and res.status == "pass"    # 1000 − 6 = 994, within 5
    assert res.expected == 994 and res.actual == 996


def test_two_rows_on_one_concept_are_summed_and_a_wrong_pairing_then_fails():
    """Several printed lines legitimately share one concept — three depreciation lines, two tax
    payments, anything a section's residual bucket absorbs — so repeated mappings add, exactly as
    the statement view and the Excel export present them.

    That also detects MORE than refusing to evaluate did. Here the second cost row does not
    belong on the concept, and the arithmetic says so: 1000 + (-600 - 900) is -500, not the 400
    reported. Skipping the relation as "ambiguous" reported nothing at all.
    """
    tpl = load_template(_pl_template())
    items = _items(revenue=1000, cost_of_sales=-600, gross_profit=400)
    items += _items(cost_of_sales=-900)

    res = _one(evaluate_structure(tpl, items), "rollup:gross_profit")
    assert res.status == "fail"
    assert res.expected == -500 and res.actual == 400
    assert res.details["component_values"]["cost_of_sales"] == "-1500"


def test_two_rows_that_do_belong_together_tie():
    """The same summing, when the two lines genuinely are one concept."""
    tpl = load_template(_pl_template())
    items = _items(revenue=1000, cost_of_sales=-600, gross_profit=-500)
    items += _items(cost_of_sales=-900)

    assert _one(evaluate_structure(tpl, items), "rollup:gross_profit").status == "pass"


def test_unweighted_op_is_refused_rather_than_guessed():
    tpl = load_template(_pl_template(op="weighted_sum"))
    report = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600, gross_profit=400))
    res = _one(report, "rollup:gross_profit")
    assert res.status == "skipped" and res.details["reason"] == "unsupported_op"


def test_mixed_scales_are_not_compared():
    """Values are not unit-normalized, so a relation across two scales is not evaluable."""
    tpl = load_template(_pl_template())
    items = _items(revenue=1000, cost_of_sales=-600, gross_profit=400)
    thousands = next(li for li in items if li.canonical_key == "cost_of_sales")
    next(iter(thousands.values.values())).unit_ctx.scale_factor = Decimal(1000)

    report = evaluate_structure(tpl, items)
    res = _one(report, "rollup:gross_profit")
    assert res.status == "skipped" and res.details["reason"] == "mixed_scale"


def test_shipped_template_relations_hold_on_a_consistent_spread():
    """The real HKFRS template's own rollups, exercised end-to-end on a small consistent set."""
    import json
    from pathlib import Path

    path = (Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"
            / "hkfrs_hk_china_template.json")
    tpl = load_template(json.loads(path.read_text()))
    report = evaluate_structure(tpl, _items(**{
        "cf_cash_flow_from_operating_activities__net_cash_from_operating_activities": 5_094_092,
        "cf_cash_flow_from_investing_activities__net_cash_used_in_investing_activities": 4_044_304,
        "cf_cash_flow_from_financing_activities__net_cash_from_financing_activities": -13_389_527,
        "cf_net_increase_decrease_in_cash_and_cash_equivalents": -4_251_131,
        "cf_opening_cash_and_cash_equivalents": 8_156_453,
        # IAS 7: closing cash is opening plus the net change PLUS the effect of exchange rate
        # movements. While the rollup omitted that third term the relation could not hold on
        # any filing that reports one — it showed up as a phantom mismatch equal to the
        # exchange effect.
        "cf_s4_effect_of_foreign_exchange_rate_changes": 26_703,
        "cf_closing_cash_and_cash_equivalents": 3_932_025,
    }))
    passed = {r.rule_id for r in report.results if r.status == "pass"}
    assert "rollup:cf_net_increase_decrease_in_cash_and_cash_equivalents" in passed
    assert "rollup:cf_closing_cash_and_cash_equivalents" in passed
    assert report.failures() == []
    # Everything the extraction didn't reach is accounted for as not-evaluable, never as a pass.
    assert report.skipped()
    assert len(report.results) == len(report.evaluated()) + len(report.skipped())


def test_stage_flags_the_involved_items_and_records_the_report():
    from app.core.models.document import DocumentModel
    from app.core.stage import PipelineContext
    from app.stages.structural import FLAG, StructuralStage

    doc = DocumentModel(filename="x.pdf")
    doc.line_items = _items(revenue=1000, cost_of_sales=-600, gross_profit=470, other_income=50)
    ctx = PipelineContext(raw_bytes=b"")
    ctx.template = load_template(_pl_template())

    StructuralStage().run(doc, ctx)

    assert doc.structural is not None and len(doc.structural.failures()) == 1
    involved = {li.canonical_key for li in doc.line_items if FLAG in li.confidence.flags}
    assert involved == {"gross_profit", "revenue", "cost_of_sales"}
    # Flagged per value too, and a failed relation can only lower the confidence signal.
    gp = next(li for li in doc.line_items if li.canonical_key == "gross_profit")
    ev = next(iter(gp.values.values()))
    assert FLAG in ev.confidence.flags and ev.confidence.validation == 0.5
    assert ev.confidence.overall < 1.0
    # A line item outside the relation is untouched.
    other = next(li for li in doc.line_items if li.canonical_key == "other_income")
    assert other.confidence.flags == []
    assert any(log.startswith("structural:evaluated=1 failed=1") for log in ctx.logs)


def test_stage_is_silent_without_a_template():
    from app.core.models.document import DocumentModel
    from app.core.stage import PipelineContext
    from app.stages.structural import StructuralStage

    doc = DocumentModel(filename="x.pdf")
    doc.line_items = _items(revenue=1000)
    ctx = PipelineContext(raw_bytes=b"")
    StructuralStage().run(doc, ctx)

    assert doc.structural is None
    assert any("structural:skipped" in log for log in ctx.logs)


def test_structural_failures_reach_the_review_queue():
    from app.api.routes.documents import _build_review

    tpl = load_template(_pl_template())
    report = evaluate_structure(tpl, _items(revenue=1000, cost_of_sales=-600, gross_profit=470))
    structural = [r.model_dump(mode="json") for r in report.results]

    review = _build_review([], "doc.pdf", "en", [], structural)
    check = next(c for c in review["checks"] if c["type"] == "structural")
    assert check["target"] == "gross_profit" and check["delta"] == "70"
    assert any(t["label"] == "Checks" and t["count"] == 1 for t in review["tabs"])
    # Relations that were only skipped raise nothing.
    quiet = evaluate_structure(tpl, _items(revenue=1000, gross_profit=400))
    assert _build_review([], "doc.pdf", "en", [],
                         [r.model_dump(mode="json") for r in quiet.results])["checks"] == []


def test_run_carries_the_structural_report_end_to_end(client):
    """A real run through the API attaches the run's template and stores the structural result —
    including the relations it could not evaluate, so coverage is auditable."""
    import time

    from tests.fixtures.generate import make_native_pdf

    doc_id = client.post("/api/v1/documents",
                         files={"file": ("bs.pdf", make_native_pdf(),
                                         "application/pdf")}).json()["id"]
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

    structural = client.get(f"/api/v1/documents/{doc_id}/run").json()["result"]["structural"]
    assert structural, "the run should record the template relations it considered"
    assert {r["status"] for r in structural} <= {"pass", "fail", "skipped"}
    # This fixture spreads onto only a handful of template lines, so no relation is complete:
    # every one is reported as not evaluable rather than passing or failing by default.
    assert all(r["status"] == "skipped" for r in structural)
    assert all(r["details"]["reason"] for r in structural)


def test_balance_identity_is_not_reported_twice():
    """The balance-sheet identity already has its own review check; the structural restatement
    of the same difference is suppressed so the analyst sees one item, not two."""
    from app.api.routes.documents import _accounting_checks

    rows = [{"canonical_key": k,
             "values": [{"basis": "consolidated", "period_label": "current", "value": str(v)}]}
            for k, v in (("bs_total_assets", 100), ("bs_total_equity_and_liabilities", 90))]
    structural = [{"rule_id": "identity:bs_balances", "kind": "identity", "status": "fail",
                   "scope_key": "consolidated/current", "expected": "90", "actual": "100",
                   "difference": "10",
                   "details": {"target": "bs_total_assets",
                               "components": ["bs_total_equity_and_liabilities"],
                               "op": "sum", "component_values": {}}}]
    types = [c["type"] for c in _accounting_checks(rows, [], "en", structural)]
    assert types == ["balance"]

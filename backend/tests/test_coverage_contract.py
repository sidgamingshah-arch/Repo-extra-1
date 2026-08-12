"""The coverage contract, re-verified end to end rather than on hand-written rows.

:mod:`app.services.coverage` exists to stop "3 relations passed" reading as "the statement is
validated", and the only way to know it still does is to run a real filing through the worker and
hold the stored result to the contract:

* THREE buckets, always all three, and they total the rows — nothing quietly leaves the arithmetic;
* both rates or neither, and no third number anywhere: ``pass / (pass + fail)`` IS the validation
  rate, and offering it alone under any name is the collapse this module prevents;
* the skip taxonomy applied to every unrun row, with the absent-statement bucket the only one
  outside the denominator;
* the alarm states firing on the conditions they name — a statement that proved nothing, and a
  guard that promised to answer unconditionally and did not.

The real-run assertions are deliberately shape-based, not thresholds: extraction quality moves, and
a contract test that fails because the mapper got better is a test nobody trusts. The alarm states
are then forced deterministically against the same shipped template and rulebook, because an alarm
that has never been seen to fire is not evidence of anything.
"""
from __future__ import annotations

import copy
import json
import time
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.models.enums import Basis
from app.core.models.line_item import ExtractedValue, LineItem
from app.schemas.loader import load_ontology, load_template
from app.services import coverage as cov_mod
from app.services.coverage import coverage
from app.services.structural_checks import STATUS_AUTHORING_ERROR, evaluate_structure

_SAMPLES = Path(__file__).resolve().parent.parent / "app" / "sample" / "templates"


@pytest.fixture(scope="module")
def raw_ontology() -> dict:
    return json.loads((_SAMPLES / "hkfrs_hk_china_v2_ontology.json").read_text())


@pytest.fixture(scope="module")
def template():
    return load_template(json.loads((_SAMPLES / "hkfrs_hk_china_template.json").read_text()))


def _ontology(raw: dict):
    return load_ontology(copy.deepcopy(raw), resolve=True)


def _facts(figures: dict, basis: Basis = Basis.CONSOLIDATED,
           period: str | None = "current") -> list[LineItem]:
    out = []
    for key, num in figures.items():
        li = LineItem(source_label=key, canonical_key=key)
        li.set_value(ExtractedValue(value=Decimal(str(num)), value_raw=Decimal(str(num)),
                                    basis=basis, period_label=period))
        out.append(li)
    return out


def _rows(report) -> list[dict]:
    return [r.model_dump(mode="json") for r in report.results]


def _real_run(client) -> list[dict]:
    """One filing through the worker with the v2 rulebook selected, as the stored rows."""
    from tests.fixtures.generate import make_native_pdf

    doc_id = client.post("/api/v1/documents",
                         files={"file": ("bs.pdf", make_native_pdf(),
                                         "application/pdf")}).json()["id"]
    ont = next(o for o in client.get("/api/v1/ontologies").json()
               if o["ontology_key"] == "hkfrs_hk_china_v2")
    tpl = next(t for t in client.get("/api/v1/templates").json()
               if t["template_key"] == ont["target_template_key"])
    client.post(f"/api/v1/documents/{doc_id}/extractions",
                json={"ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    for _ in range(200):
        if client.get(f"/api/v1/documents/{doc_id}/run").json().get("status") == "succeeded":
            break
        time.sleep(0.05)
    run = client.get(f"/api/v1/documents/{doc_id}/run").json()
    assert run["status"] == "succeeded", run
    return run["result"]["structural"]


def test_the_coverage_contract_holds_end_to_end_on_a_real_filing(client, template, raw_ontology):
    rows = _real_run(client)
    report = coverage(rows)
    agg = report.aggregate
    per_statement = [cov for _n, cov in sorted(report.statements.items())]

    # --- three buckets, always all three, and they account for every row ------------------------
    assert rows and agg.buckets.total == len(rows)
    assert (agg.buckets.passed + agg.buckets.failed + agg.buckets.skipped) == len(rows)
    assert sum(c.buckets.total for c in per_statement) == len(rows)
    # The run verified something and nowhere near everything, which is the situation the contract
    # is written for — a partial verification must never render as a pass.
    assert agg.evaluated > 0 and agg.buckets.skipped > 0
    assert agg.coverage_rate < 1.0 and agg.status != cov_mod.PASSED

    # --- both rates or neither, and no collapsed single score anywhere --------------------------
    for cov in [agg, *per_statement]:
        emitted = cov.as_dict()
        assert {"passed", "failed", "skipped", "evaluated", "declarable"} <= emitted.keys()
        assert ("validation_rate" in emitted) == ("coverage_rate" in emitted)
        # pass/(pass+fail) is the validation rate; under any other name it is the collapse.
        assert not {"pass_rate", "score", "rate", "success_rate", "health"} & emitted.keys()
        assert emitted["validation_rate"] == (
            None if cov.evaluated == 0 else round(cov.buckets.passed / cov.evaluated, 4))
        assert emitted["coverage_rate"] == (
            None if cov.declarable == 0 else round(cov.evaluated / cov.declarable, 4))
    # Both rates travel in the run log too, each with the fraction it was computed from, so a
    # reader cannot take one for the other.
    line = report.headline()
    assert f"({agg.buckets.passed}/{agg.evaluated})" in line
    assert f"({agg.evaluated}/{agg.declarable})" in line

    # --- the skip taxonomy, applied to every row that did not run ------------------------------
    unrun = [r for r in rows if r["status"] not in ("pass", "fail")]
    assert len(unrun) == agg.buckets.skipped
    assert all(r["details"].get("reason") in cov_mod.TAXONOMY for r in unrun)
    assert sum(agg.skips.values()) == agg.buckets.skipped
    assert cov_mod.UNCLASSIFIED not in agg.skips
    # Only the absent-statement rows leave the denominator; every other unrun row stays in it.
    assert agg.declarable == agg.evaluated + sum(
        n for bucket, n in agg.skips.items() if bucket not in cov_mod.NOT_DECLARABLE)
    for cov in per_statement:
        if cov.status == cov_mod.ABSENT:
            assert set(cov.skips) <= set(cov_mod.NOT_DECLARABLE)

    # --- a healthy run raises no defect alarm --------------------------------------------------
    # Every relation and guard the shipped rulebook declares resolves against the shipped
    # template, so nothing here is unrunnable and nothing blocking is unenforceable.
    assert not [a for a in report.alarms
                if a["code"] in (cov_mod.ALARM_PIPELINE_DEFECT, cov_mod.ALARM_UNENFORCEABLE)]
    assert report.unenforceable() == [] and "unenforceable_blocking=0" in line

    # --- UNVALIDATED: a statement whose every declarable relation was skipped -------------------
    # Forced, so the alarm is seen firing rather than assumed: one opening-cash figure makes the
    # cash flow statement PRESENT — so its relations are declarable — while none of them can run.
    ont = _ontology(raw_ontology)
    starved = coverage(_rows(evaluate_structure(
        template, _facts({"cf_opening_cash_and_cash_equivalents": 8_156_453}), ontology=ont)))
    cash = starved.statements["cash_flow"]
    assert cash.evaluated == 0 and cash.declarable > 0
    assert cash.status == cov_mod.UNVALIDATED and cash.status != cov_mod.PASSED
    assert cash.buckets.failed == 0                 # no failures, and nothing proved
    assert cash.validation_rate is None             # 0/0 is not 1.0
    assert "cash_flow" in starved.unvalidated()
    # One alarm per unvalidated statement, no more and no fewer.
    assert sorted(a["statement"] for a in starved.alarms
                  if a["code"] == cov_mod.ALARM_UNVALIDATED) == starved.unvalidated()

    # --- PIPELINE_DEFECT: an unconditional guard that answered nothing -------------------------
    # "…together with any of its listed components" reads its list from the rulebook, so emptying
    # that list leaves the guard nothing to compare. Its precondition is "always", so having no
    # answer cannot be a fact about the filing.
    blinded = copy.deepcopy(raw_ontology)
    group = next(g for g in blinded["global_rules"]["mutually_exclusive_groups"]
                 if g["aggregate"] == "bs_equity__reserves")
    group["components"] = []
    report2 = evaluate_structure(template, _facts({"bs_equity__reserves": 900}),
                                ontology=_ontology(blinded))
    guard = next(r for r in report2.results
                 if r.rule_id == "guard:mutually_exclusive:bs_equity__reserves")
    assert guard.status == STATUS_AUTHORING_ERROR and guard.details["precondition"] == "always"
    cov2 = coverage(_rows(report2))
    assert [a for a in cov2.alarms
            if a["code"] == cov_mod.ALARM_PIPELINE_DEFECT
            and a["rule_id"] == guard.rule_id and a["precondition"] == "always"]
    # …and it is not filed as something better extraction would fix.
    assert cov2.statements[guard.details["statement"]].skips.get("UNEVALUABLE_RULE") == 1

    # A guard that genuinely needs something of the filing is the opposite case: consolidation
    # eliminates investments in subsidiaries, so on a company-only column that guard has nothing
    # to say. Its precondition says so, so the skip is recoverable coverage, not an alarm.
    company = evaluate_structure(
        template, _facts({"bs_non_current_assets__investments_in_subsidiaries": 4_500_000},
                         basis=Basis.STANDALONE), ontology=ont)
    skipped = next(r for r in company.results if r.rule_id.startswith(
        "guard:consolidation_eliminated:"))
    assert skipped.status == "skipped" and skipped.details["reason"] == "precondition_absent"
    assert skipped.details["precondition"] == "a consolidated column"
    cov3 = coverage(_rows(company))
    assert not [a for a in cov3.alarms if a["code"] == cov_mod.ALARM_PIPELINE_DEFECT]
    assert cov3.statements["balance_sheet"].recoverable_skips >= 1

"""Extraction progress: live, per stage, and a pinned pair the API has to refuse.

WHAT WAS BROKEN, MEASURED. ``Pipeline.run`` emits a progress event before each of its stages and
once more when it finishes, and ``ExtractionRun.progress`` is a real column that
``GET /extractions/{run_id}`` has always served — but the worker called ``run_extraction`` WITHOUT a
``progress_cb``, which defaults to None. Every emit was a no-op: the row held
``{"phase": "queued"}`` for the entire duration of a run and then jumped to ``{"phase": "done"}``,
and ``run.logs`` was written once, at the very end. A client polling once a second for the whole of
a multi-stage LLM run had nothing to show, and the endpoint's stage list did not exist at all.

HOW THESE TESTS SEE A RUNNING RUN. Under ``TestClient`` a FastAPI BackgroundTask finishes inside the
POST, so no poll can catch a stage in flight. Instead ``_recorded_progress`` listens for UPDATEs on
the run row, which is exactly where the mechanism under test writes: it records what was actually
COMMITTED to the database while the pipeline ran. Drop ``progress_cb`` from the worker's
``run_extraction`` call and every one of those intermediate rows disappears.
"""
from __future__ import annotations

import contextlib
import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

pytest.importorskip("fitz")

from tests.fixtures.generate import make_native_pdf


def _stage_names() -> list[str]:
    """The pipeline's own ordered stage names — the answer every assertion here is measured
    against, never a literal list copied into this file."""
    from app.core.pipeline import default_pipeline

    return [stage.name for stage in default_pipeline().stages]


@contextlib.contextmanager
def _recorded_progress():
    """Every ``progress`` record committed to a run row inside the block — with the ``logs`` value
    that landed with it, and the run's ``status``/``result`` at that moment — in commit order.

    The INSERT is listened for as well as the UPDATEs, because the queued record only exists on the
    insert: by the time the POST returns, the first stage has already overwritten it.
    """
    from app.db.models import ExtractionRun

    records: list[tuple[dict, str, str, dict | None]] = []

    def _capture(mapper, connection, target) -> None:
        records.append((dict(target.progress or {}), target.logs or "",
                        target.status, target.result))

    for moment in ("after_insert", "after_update"):
        event.listen(ExtractionRun, moment, _capture)
    try:
        yield records
    finally:
        for moment in ("after_insert", "after_update"):
            event.remove(ExtractionRun, moment, _capture)


def _upload(client, name: str = "progress.pdf") -> str:
    return client.post("/api/v1/documents",
                       files={"file": (name, make_native_pdf(), "application/pdf")}).json()["id"]


def _run_to_completion(client, doc_id: str, body: dict | None = None) -> str:
    started = client.post(f"/api/v1/documents/{doc_id}/extractions", json=body or {})
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    for _ in range(200):
        status = client.get(f"/api/v1/extractions/{run_id}").json()["status"]
        if status in {"succeeded", "failed"}:
            return run_id
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never settled")


def _shipped_pins(client) -> tuple[dict, dict]:
    """The shipped rulebook and the template it is written for, as the UI pins them."""
    onts = client.get("/api/v1/ontologies").json()
    ont = next(o for o in onts if o["ontology_key"] == "hkfrs_hk_china")
    tpls = client.get("/api/v1/templates").json()
    tpl = next(t for t in tpls if t["template_key"] == ont["target_template_key"])
    return ont, tpl


def test_progress_moves_through_the_named_stages_of_the_real_pipeline(client):
    """The whole point of the unit: ``run.progress`` advances, stage by named stage, WHILE the run
    runs — not once at the end.

    Every stage name asserted here comes from ``default_pipeline()``, so this measures the pipeline
    that runs rather than a list someone wrote down. Remove ``progress_cb`` from the worker's
    ``run_extraction`` call and nothing but ``queued``/``done`` is ever committed, so the first
    assertion below has nothing to stand on.
    """
    names = _stage_names()
    doc_id = _upload(client)
    with _recorded_progress() as records:
        run_id = _run_to_completion(client, doc_id)
    assert client.get(f"/api/v1/extractions/{run_id}").json()["status"] == "succeeded"

    staged = [p for p, _, _, _ in records if p.get("stage")]
    assert staged, ("no per-stage progress was ever committed — the pipeline's progress emits are "
                    "going nowhere, which is the defect this unit exists to close")

    # The stages reported are the pipeline's, in the pipeline's order, and each one's index is its
    # own index in that pipeline — not a running counter that happens to agree.
    reported = [p["stage"] for p in staged]
    assert reported == names, reported
    assert [p["stage_index"] for p in staged] == list(range(len(names)))
    assert all(p["stage_count"] == len(names) for p in staged)

    # `stages_done` is what has actually FINISHED at each emit: the emit precedes its stage, so it
    # lists everything before it and never the stage being announced.
    for p in staged:
        assert p["stages_done"] == names[:p["stage_index"]], p
        assert p["stage"] not in p["stages_done"]

    pcts = [p["pct"] for p, _, _, _ in records]
    assert pcts == sorted(pcts), pcts
    assert pcts[0] < pcts[-1] == 1.0

    # Nothing half-built was ever published, in either direction.
    #
    # No partial RESULT: every record committed while the run was `running` came with no result on
    # the row. That is what the per-emit short-lived session buys — the worker's own session is
    # assembling `result` across many statements while these fire, and committing THAT session from
    # the callback would hand a poller a partial spread it would render.
    #
    # And no premature COMPLETION: the pipeline's own closing emit is `("done", 1.0)`, but the worker
    # then serialises the rows, scans the disclosures and detects the entity before it commits a
    # result. A record claiming 100% or `done` while the row still says `running` is a completion a
    # client would act on and find nothing behind.
    for p, _, status, result in records:
        if status == "running":
            assert result is None, p
            assert p["phase"] != "done" and p["pct"] < 1.0, p

    # The terminal record is the same shape, with every stage ticked off.
    final = client.get(f"/api/v1/extractions/{run_id}").json()["progress"]
    assert final["phase"] == "done" and final["pct"] == 1.0
    assert final["stages_done"] == names and final["stage_index"] == len(names)


def test_the_endpoint_serves_the_pipelines_own_stage_list(client):
    """``stages`` is read off the pipeline, so it cannot fall out of step with it.

    A hardcoded copy would satisfy the first assertion on the day it was written and fail the
    second, which swaps the pipeline for a different one and demands the endpoint say so.
    """
    doc_id = _upload(client)
    run_id = _run_to_completion(client, doc_id)
    served = client.get(f"/api/v1/extractions/{run_id}").json()
    assert served["stages"] == _stage_names()

    from app.core.pipeline import Pipeline

    class _Probe:
        def __init__(self, name: str) -> None:
            self.name = name

        def run(self, doc, ctx):  # pragma: no cover — never run; only its name is read
            return doc

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.core.pipeline.default_pipeline",
                   lambda: Pipeline(stages=[_Probe("first"), _Probe("second")]))
        assert client.get(f"/api/v1/extractions/{run_id}").json()["stages"] == ["first", "second"]


def test_the_log_tail_is_flushed_as_stages_complete_not_only_at_the_end(client):
    """``run.logs`` used to be written once, when the run settled, so a screen had nothing to show
    for the whole run. It now moves with the progress record."""
    names = _stage_names()
    doc_id = _upload(client)
    with _recorded_progress() as records:
        run_id = _run_to_completion(client, doc_id)

    # By the time the pipeline announces its SECOND stage, the first stage's log lines are already
    # on the row. (At the first stage there is genuinely nothing logged yet, and claiming otherwise
    # would be inventing a line.)
    mid = [logs for p, logs, _, _ in records if p.get("stage") == names[1]]
    assert mid, f"the run never reported reaching {names[1]!r}"
    assert mid[0].strip(), "the log tail was still empty two stages in"
    assert f"stage:{names[0]}:done" in mid[0], mid[0]

    served = client.get(f"/api/v1/extractions/{run_id}").json()
    assert served["log_tail"].strip()
    assert f"stage:{names[-1]}:done" in served["log_tail"]


def test_the_log_tail_is_a_tail_and_not_the_whole_log():
    """A log of a thousand lines is not something to ship on every poll — and mid-run flush and
    served value have to agree on how much of it there is, or the window would appear to change
    size the moment the run settles."""
    from app.api.routes.extractions import _LOG_TAIL_LINES, _log_tail

    lines = [f"line {i}" for i in range(_LOG_TAIL_LINES * 3)]
    assert _log_tail(lines).splitlines() == lines[-_LOG_TAIL_LINES:]
    assert _log_tail(lines[:5]).splitlines() == lines[:5]
    assert _log_tail([]) == "" and _log_tail(None) == ""


def test_progress_says_when_the_run_started_and_how_long_it_has_taken(client):
    """``started_at`` + ``elapsed_ms``: a duration a screen can show without keeping its own clock,
    and derived at each emit rather than accumulated."""
    doc_id = _upload(client)
    with _recorded_progress() as records:
        run_id = _run_to_completion(client, doc_id)

    # ONE clock for the whole run, queued record included. Stamping a second one when the worker
    # picks the run up makes `started_at` jump forward and `elapsed_ms` fall back towards zero
    # mid-poll, and loses the queued wait — which is time the reader spent waiting.
    stamps = {p["started_at"] for p, _, _, _ in records}
    assert len(stamps) == 1, f"the run reported more than one start time: {stamps}"
    started = datetime.fromisoformat(stamps.pop())
    assert started.tzinfo is not None, "started_at must be unambiguous about its timezone"

    elapsed = [p["elapsed_ms"] for p, _, _, _ in records]
    assert elapsed == sorted(elapsed), elapsed

    final = client.get(f"/api/v1/extractions/{run_id}").json()["progress"]
    assert final["started_at"] == started.isoformat()
    assert final["elapsed_ms"] > 0, "a run of fourteen stages cannot have taken zero milliseconds"

    # And it is the run's OWN start time, not a second stamp taken beside it: `created_at` and
    # `started_at` are one instant, so the elapsed time a screen shows is measured from the moment
    # the run row says it began.
    from app.db.base import SessionLocal
    from app.db.models import ExtractionRun

    with SessionLocal() as s:
        created = s.get(ExtractionRun, run_id).created_at
    # SQLite hands back a naive datetime; the column stores UTC (models._now).
    assert created.replace(tzinfo=timezone.utc) == started


def test_the_recorder_counts_stage_entries_instead_of_looking_stage_names_up(monkeypatch):
    """Two assumptions a real pipeline is allowed to break, held here against a three-stage pipeline
    that runs its first stage twice — an ordinary thing to do, and what ``GapClosingStage`` already
    exists to do.

    Looking the current stage's index up BY NAME sends progress backwards on the second pass, and a
    terminal record hardcoded to 100% contradicts its own stage count when the pipeline stops early
    (which it does, on an integrity blocker).
    """
    from app.api.routes import extractions as ext

    written: list[dict] = []
    monkeypatch.setattr(ext, "pipeline_stage_names", lambda: ["a", "b", "a"])
    monkeypatch.setattr(ext._RunProgress, "_write",
                        lambda self, payload: written.append(payload))
    began = datetime(2026, 1, 1, tzinfo=timezone.utc)

    whole = ext._RunProgress("probe-whole", began)
    for phase, pct in (("a", 0.0), ("b", 0.333), ("a", 0.667), ("done", 1.0)):
        whole(phase, pct)

    assert [p["stage"] for p in written] == ["a", "b", "a"]
    assert [p["stage_index"] for p in written] == [0, 1, 2]
    assert [p["stages_done"] for p in written] == [[], ["a"], ["a", "b"]]
    assert all(p["stage_count"] == 3 for p in written)
    # The pipeline's closing emit publishes nothing of its own — `settle` does, once the run is
    # genuinely over — and it reports the whole traversal, repeat included.
    assert len(written) == 3
    settled = whole.settle("done")
    assert settled["stages_done"] == ["a", "b", "a"] and settled["pct"] == 1.0

    # Stopped after one stage: done, and honest about how much of the pipeline that was.
    halted = ext._RunProgress("probe-halted", began)
    halted("a", 0.0)
    halted("done", 1.0)
    early = halted.settle("done")
    assert early["phase"] == "done" and early["stage_index"] == 1 and early["stage_count"] == 3
    assert early["pct"] == round(1 / 3, 3), "a run that ran 1 of 3 stages is not 100% of a pipeline"


def test_a_run_recorded_before_this_contract_serves_no_progress_rather_than_half_of_it(client):
    """``init_db`` uses ``create_all``, so runs written by the old code are still on disk holding
    ``{"phase": …, "pct": …}`` and nothing else. ``ExtractionProgress`` declares every field
    required, so passing that off as one of these records hands a screen ``undefined`` where the type
    promises a number — and completing it would mean inventing the stage count and start time of a
    run whose pipeline is not recoverable."""
    from app.db.base import SessionLocal
    from app.db.models import ExtractionRun

    doc_id = _upload(client)
    # A fresh id, removed again: the suite shares one database, and a hand-written run left behind
    # here is a run every later test that enumerates them has to know about.
    run_id = f"legacy-shaped-{uuid.uuid4().hex[:12]}"
    with SessionLocal() as s:
        s.add(ExtractionRun(id=run_id, document_id=doc_id, status="succeeded",
                            options={}, progress={"phase": "done", "pct": 1.0},
                            result={"rows": []}))
        s.commit()
    try:
        served = client.get(f"/api/v1/extractions/{run_id}").json()
        assert served["progress"] is None
        # The run still reports how it ended, and still gets the stage list and the log tail.
        assert served["status"] == "succeeded"
        assert served["stages"] == _stage_names()
    finally:
        with SessionLocal() as s:
            s.delete(s.get(ExtractionRun, run_id))
            s.commit()


def test_a_run_that_pins_a_template_its_rulebook_was_not_written_for_is_refused(client):
    """A rulebook declares the template it targets. Pinning it against a DIFFERENT template maps
    every caption with a rulebook validated against a template the spread never uses — the
    mechanism behind a cost-of-sales line turning up inside other income. The run succeeds and the
    spread is quietly wrong, so the pair is refused at the door instead."""
    ont, tpl = _shipped_pins(client)
    other = client.post("/api/v1/templates", json={"definition": {
        "template_key": "u1_unrelated_tpl", "name": "Unrelated", "statements": [],
    }})
    assert other.status_code == 201, other.text

    doc_id = _upload(client)
    refused = client.post(f"/api/v1/documents/{doc_id}/extractions", json={
        "ontology_version_id": ont["id"], "template_version_id": other.json()["id"]})
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    # Both keys named, because "mismatch" alone does not tell the caller which of the two to change.
    assert "u1_unrelated_tpl" in detail["message"]
    assert ont["target_template_key"] in detail["message"]
    assert detail["template_key"] == "u1_unrelated_tpl"
    assert detail["ontology_target_template_key"] == ont["target_template_key"]

    # No run was created for the refused pair — a 422 that still queued a run would extract with
    # the very pairing it just rejected.
    from app.db.base import SessionLocal
    from app.db.models import ExtractionRun

    with SessionLocal() as s:
        assert s.query(ExtractionRun).filter_by(document_id=doc_id).count() == 0

    # The coherent pin — the shipped template and its own rulebook — is still accepted.
    ok = client.post(f"/api/v1/documents/{doc_id}/extractions", json={
        "ontology_version_id": ont["id"], "template_version_id": tpl["id"]})
    assert ok.status_code == 202, ok.text


def test_pinning_only_one_of_the_two_stays_legal(client):
    """Both fields are optional and a run may name just one. The cross-check must refuse a
    CONTRADICTION, not a run that made only half the choice."""
    ont, tpl = _shipped_pins(client)
    doc_id = _upload(client)
    for body in ({"ontology_version_id": ont["id"]}, {"template_version_id": tpl["id"]}, {}):
        r = client.post(f"/api/v1/documents/{doc_id}/extractions", json=body)
        assert r.status_code == 202, (body, r.text)


def test_a_failed_run_reports_failed_progress_and_names_the_stage_it_died_in(client):
    """Progress must settle at ``failed`` — and the recorder must not swallow the failure on its
    way there, which is what a bare ``except`` around the whole task would do."""
    names = _stage_names()
    doc_id = _upload(client)

    def _explode(self, doc, ctx):
        raise RuntimeError("structural stage exploded")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.stages.structural.StructuralStage.run", _explode)
        run_id = _run_to_completion(client, doc_id)

    served = client.get(f"/api/v1/extractions/{run_id}").json()
    assert served["status"] == "failed", served["progress"]
    progress = served["progress"]
    assert progress["phase"] == "failed"
    # The stage that was in flight is named, and is NOT counted as done.
    assert progress["stage"] == "structural"
    assert progress["stages_done"] == names[:-1]
    # A run that died in its last stage never claims to have finished the pipeline.
    assert progress["pct"] < 1.0 and progress["stage_index"] == len(names) - 1
    assert "RuntimeError" in served["log_tail"]


def test_a_start_stamp_with_no_timezone_still_times_the_run(client):
    """``_run_extraction_task`` is called directly by re-run scripts and probes (see
    ``test_rulebook_plumbing``), so its start stamp is not always one this module wrote. A stamp with
    no zone on it makes every ``elapsed_ms`` subtraction raise ``TypeError`` — on the failure path
    too, which escapes the task and leaves the run at ``running`` with nothing ever committed."""
    from app.api.routes.extractions import _run_extraction_task
    from app.db.base import SessionLocal
    from app.db.models import Document, ExtractionRun

    doc_id = _upload(client)
    run_id = f"naive-stamp-{uuid.uuid4().hex[:12]}"
    with SessionLocal() as s:
        doc = s.get(Document, doc_id)
        object_key, filename = doc.object_key, doc.filename
        s.add(ExtractionRun(id=run_id, document_id=doc_id, status="running",
                            options={}, progress={}, result=None))
        s.commit()
    try:
        _run_extraction_task(run_id, object_key, filename, {}, "probe", "stub", "stub",
                             None, "2026-01-01T00:00:00")
        with SessionLocal() as s:
            run = s.get(ExtractionRun, run_id)
            assert run.status == "succeeded", run.logs
            assert run.progress["started_at"].endswith("+00:00"), run.progress["started_at"]
            assert run.progress["elapsed_ms"] > 0
    finally:
        with SessionLocal() as s:
            s.delete(s.get(ExtractionRun, run_id))
            s.commit()


def test_a_failure_before_the_pipeline_starts_is_recorded_on_the_run(client):
    """Building the recorder builds the pipeline, to read its stage list off it. That has to happen
    inside the worker's failure path: a stage module that will not import would otherwise kill the
    background task with the run row untouched — left at ``running``, which is the one state a
    polling client never stops waiting on."""
    from app.api.routes import extractions as ext

    doc_id = _upload(client)

    def _boom(self, run_id, started_at):
        raise ImportError("a stage module will not import")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ext._RunProgress, "__init__", _boom)
        run_id = _run_to_completion(client, doc_id)

    served = client.get(f"/api/v1/extractions/{run_id}").json()
    assert served["status"] == "failed"
    assert served["progress"]["phase"] == "failed"
    # No pipeline was ever assembled, and the record claims no stages rather than inventing them.
    assert served["progress"]["stage_count"] == 0
    assert served["progress"]["stages_done"] == []
    assert "ImportError" in served["log_tail"]


def test_a_progress_write_that_fails_never_fails_the_extraction(client):
    """A progress record is a report ABOUT the run, not part of it. A run that reached its rows
    must not be recorded as failed because a status write did not land — and the reason it did not
    land has to be said out loud rather than swallowed."""
    from app.api.routes import extractions as ext

    doc_id = _upload(client)

    def _refuse(self, payload):
        raise RuntimeError("progress table on fire")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ext._RunProgress, "_write", _refuse)
        run_id = _run_to_completion(client, doc_id)

    served = client.get(f"/api/v1/extractions/{run_id}").json()
    assert served["status"] == "succeeded", served["log_tail"]
    assert served["result"]["rows"]
    # Degraded loudly, not silently: the run's own log names what stopped its progress reporting.
    assert "progress:write_failed" in served["log_tail"]
    assert "progress table on fire" in served["log_tail"]

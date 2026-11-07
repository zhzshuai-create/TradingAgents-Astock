"""P1-10 acceptance tests: crash detection and interrupted.

SM-13: running / pause_requested / cancel_requested rows left without a live
       worker all become interrupted in one startup reconcile pass.
SM-I04: resume on an interrupted row is rejected; only retry with
        resume_from_checkpoint (an explicit idempotent request) creates a job.
CB-01..CB-06: one case per crash boundary in crash-boundaries.md, including
        the B3/B4 reconcile_notes with seq NULL.
GF-21: queued stays queued; a paused job survives reconciliation while its
       checkpoint files are readable and becomes interrupted
       (checkpoint_missing) when they are gone.
Switch: TA_STARTUP_RECONCILE=0 is the rollback path and leaves every row as
        it was. A live foreign lease also skips the scan.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_crash_recovery.py -q
"""

from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.fake_analysis_graph as fake  # noqa: E402
from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobStage, Report  # noqa: E402
from backend.app.services.analysis_runner import (  # noqa: E402
    FakeAnalysisExecutor,
    StageProgress,
)
from backend.app.services.job_service import (  # noqa: E402
    CST,
    JobService,
    StatsSnapshot,
)
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.worker.main import (  # noqa: E402
    Worker,
    startup_reconcile_enabled,
)
from backend.app.worker.reconcile import Reconciler  # noqa: E402

BACKEND = ROOT / "backend"
TODAY = "2026-10-30"
CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}
SERVER_CONFIG = ServerConfig(
    graph_version="graph-v1",
    llm_profiles=("deepseek-default",),
    parallel_analysts=True,
    stage_toggles={"policy": True, "hot_money": True, "lockup": True},
    write_mode="next",
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    command.upgrade(_alembic_config(), "head")

    clock = _Clock(datetime(2026, 10, 30, 9, 0, tzinfo=CST))
    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    jobs = JobService(engine, SERVER_CONFIG, clock=clock, reports=reports)
    app = create_app(
        service=jobs, server_config=SERVER_CONFIG, report_store=reports
    )
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            engine=engine,
            jobs=jobs,
            reports=reports,
            clock=clock,
            client=client,
            lease=lambda **kwargs: LeaseService(engine, clock=clock, **kwargs),
        )
    finally:
        client.close()
        engine.dispose()


def _create(env, ticker: str = "000629") -> str:
    outcome = env.jobs.create_job(
        {"ticker": ticker, "analysis_date": TODAY, "config": dict(CONFIG)},
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def _claim(env, job_id: str, owner: str = "worker-crashed") -> None:
    """Start a run, then vanish: job running, no live global lease."""
    lease = env.lease()
    assert lease.acquire(owner) is True
    claimed = lease.claim_next_job(owner)
    assert claimed is not None and claimed.id == job_id
    assert lease.release(owner) is True


def _status(env, job_id: str) -> str:
    job = env.jobs.get_job(job_id)
    assert job is not None
    return job.status


def _detail(env, job_id: str) -> dict:
    response = env.client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    return response.json()


def _events(env, job_id: str) -> list[JobEvent]:
    with Session(env.engine) as session:
        return list(
            session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.id)
            )
        )


def _sse(env, job_id: str) -> list[JobEvent]:
    return [event for event in _events(env, job_id) if event.seq is not None]


def _stage_rows(env, job_id: str) -> dict[str, JobStage]:
    with Session(env.engine) as session:
        return {
            row.stage_id: row
            for row in session.scalars(
                select(JobStage).where(JobStage.job_id == job_id)
            )
        }


def _report_row(env, job_id: str) -> Report | None:
    with Session(env.engine) as session:
        return session.scalars(
            select(Report).where(Report.job_id == job_id)
        ).first()


def _job_count(env) -> int:
    with Session(env.engine) as session:
        return session.scalar(select(func.count()).select_from(Job))


def _retry(env, job_id: str, *, mode: str = "same_config"):
    return env.client.post(
        f"/api/v1/jobs/{job_id}/retry",
        json={"mode": mode},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


def _golden_report(job_id: str) -> dict:
    graph = fake.FakeAnalysisGraph("000629", TODAY)
    return graph.build_report(
        job_id, generated_at=datetime(2026, 10, 30, 9, 0, tzinfo=CST)
    )


def _cumulative_stats(count: int) -> StatsSnapshot:
    specs = fake.STAGES[:count]
    return StatsSnapshot(
        model_calls=sum(spec.model_calls for spec in specs),
        tokens_in=sum(spec.tokens_in for spec in specs),
        tokens_out=sum(spec.tokens_out for spec in specs),
        elapsed_ms=sum(spec.duration_ms for spec in specs),
    )


def _complete_stage(env, job_id: str, index: int) -> None:
    spec = fake.STAGES[index - 1]
    env.jobs.start_stage(job_id, spec.id, index=index, total=12)
    path = env.reports.write_stage_report(
        job_id, spec.id, f"{spec.name}报告：{spec.id}"
    )
    env.jobs.finish_stage(
        job_id,
        spec.id,
        index=index,
        total=12,
        stats=_cumulative_stats(index),
        report_path=path,
        duration_ms=spec.duration_ms,
    )


class _TriggerAfterStage:
    """Call a control action right after one fake stage reports done."""

    name = "trigger-after-stage"

    def __init__(self, action, after_stage: str) -> None:
        self._inner = FakeAnalysisExecutor()
        self._action = action
        self._after = after_stage
        self._fired = False

    def run(self, request, *, on_stage=None, on_chunk=None):
        def hook(progress: StageProgress) -> None:
            if on_stage is not None:
                on_stage(progress)
            if (
                not self._fired
                and progress.phase == "done"
                and progress.stage_id == self._after
            ):
                self._fired = True
                self._action(request.job_id)

        return self._inner.run(request, on_stage=hook, on_chunk=on_chunk)


def _run(env, executor=None, *, reconcile: bool = True):
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner="worker-test",
        executor=executor,
        reconcile_on_start=reconcile,
    )
    assert worker.acquire() is True
    try:
        outcome = worker.run_once()
        assert outcome is not None
        return outcome
    finally:
        worker.shutdown()


def _pause_job(env, job_id: str, after_stage: str = "news") -> None:
    executor = _TriggerAfterStage(
        lambda job: env.jobs.request_pause(job), after_stage
    )
    outcome = _run(env, executor)
    assert outcome.stopped == "paused"
    assert _status(env, job_id) == "paused"


def _reconcile(env, *, owner: str = "worker-startup"):
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner=owner,
        reconcile_on_start=True,
    )
    assert worker.acquire() is True
    return worker


def _interrupted_payload(
    from_status: str, detail: str
) -> dict[str, object]:
    return {
        "from": from_status,
        "to": "interrupted",
        "reason": "reconcile",
        "detail": detail,
        "pending_action": None,
        "error": None,
    }


def test_sm13_worker_held_rows_are_interrupted_after_the_lease_lapses(env):
    running_id = _create(env, ticker="000629")
    _claim(env, running_id)

    pause_id = _create(env, ticker="600519")
    _claim(env, pause_id)
    assert env.jobs.request_pause(pause_id).accepted is True

    cancel_id = _create(env, ticker="000001")
    _claim(env, cancel_id)
    assert env.jobs.request_cancel(cancel_id).accepted is True

    env.clock.advance(minutes=5)
    worker = _reconcile(env)
    try:
        expected = {
            running_id: ("running", "lease_expired", 1),
            pause_id: ("pause_requested", "lease_expired", 2),
            cancel_id: ("cancel_requested", "lease_expired", 2),
        }
        for job_id, (before, detail, prior_events) in expected.items():
            job = env.jobs.get_job(job_id)
            assert job.status == "interrupted"
            assert job.pending_action is None
            assert job.lease_owner is None
            assert job.finished_at == env.clock.now.isoformat(timespec="seconds")

            sse = _sse(env, job_id)
            assert len(sse) == prior_events + 1
            assert sse[-1].type == "status_changed"
            assert sse[-1].payload == _interrupted_payload(before, detail)
            assert sse[-1].seq == prior_events + 1
            assert not any(
                event.type == "reconcile_note" for event in _events(env, job_id)
            )
            assert _stage_rows(env, job_id) == {}
            assert _report_row(env, job_id) is None

        assert worker.claim() is None
    finally:
        worker.shutdown()

    for job_id in expected:
        assert _detail(env, job_id)["allowed_actions"] == [
            "resume_from_checkpoint",
            "retry",
            "reanalyze",
        ]


def test_sm_i04_interrupted_refuses_resume_and_only_retry_resumes(env):
    job_id = _create(env)
    _claim(env, job_id)
    worker = _reconcile(env)
    worker.shutdown()
    assert _status(env, job_id) == "interrupted"
    before_events = _events(env, job_id)

    resume = env.client.post(
        f"/api/v1/jobs/{job_id}/actions", json={"action": "resume"}
    )
    assert resume.status_code == 409
    assert resume.json()["error"] == {
        "code": "illegal_transition",
        "message": "当前状态不支持这个操作",
        "request_id": resume.headers["X-Request-Id"],
        "details": {"from": "interrupted", "action": "resume", "rule": None},
    }
    assert _status(env, job_id) == "interrupted"
    assert before_events, "the claim and the reconcile must have events"
    before_sse = [
        (event.seq, event.type, dict(event.payload))
        for event in before_events
        if event.seq
    ]
    assert [
        (event.seq, event.type, dict(event.payload))
        for event in _sse(env, job_id)
    ] == before_sse
    audit = [
        event
        for event in _events(env, job_id)
        if event.type == "transition_rejected"
    ]
    assert len(audit) == 1 and audit[0].seq is None

    resumed = _retry(env, job_id, mode="resume_from_checkpoint")
    assert resumed.status_code == 201
    body = resumed.json()
    assert body["job_id"] != job_id
    assert body["resume_of_job_id"] == job_id
    assert body["retry_of_job_id"] is None
    assert body["resume_from_stage"] == "market"
    assert body["status"] == "queued"
    assert _status(env, job_id) == "interrupted"
    assert _job_count(env) == 2


def test_cb01_b1_queued_survives_reconcile_and_is_claimed(env):
    job_id = _create(env)
    worker = _reconcile(env)
    try:
        assert _status(env, job_id) == "queued"
        assert _sse(env, job_id) == []
        assert _detail(env, job_id)["stages"][0]["status"] == "pending"

        outcome = worker.run_once()
        assert outcome is not None
        assert outcome.result is not None
    finally:
        worker.shutdown()

    assert _status(env, job_id) == "succeeded"
    assert _sse(env, job_id)[0].payload["to"] == "running"
    assert _job_count(env) == 1


def test_cb02_b2_run_without_artifacts_is_interrupted_without_rerun(env):
    job_id = _create(env)
    _claim(env, job_id)
    env.clock.advance(minutes=5)

    worker = _reconcile(env)
    try:
        assert _status(env, job_id) == "interrupted"
        sse = _sse(env, job_id)
        assert [event.seq for event in sse] == [1, 2]
        assert sse[0].payload["from"] == "queued"
        assert sse[1].payload == _interrupted_payload(
            "running", "lease_expired"
        )
        assert worker.claim() is None
    finally:
        worker.shutdown()

    job = env.jobs.get_job(job_id)
    assert job.resume_from_stage == "market"
    assert not any(e.type == "stats" for e in _events(env, job_id))
    assert _report_row(env, job_id) is None
    assert _stage_rows(env, job_id) == {}
    detail = _detail(env, job_id)
    assert detail["stages"] and all(
        stage["status"] == "pending" for stage in detail["stages"]
    )
    assert detail["reconcile_notes"] == []


def test_cb03_b3_stage_artifact_without_done_event_notes_and_resumes(env):
    job_id = _create(env)
    _claim(env, job_id)
    _complete_stage(env, job_id, 1)
    _complete_stage(env, job_id, 2)
    env.jobs.start_stage(job_id, "news", index=3, total=12)
    env.reports.write_stage_report(job_id, "news", "新闻报告：B3")

    worker = _reconcile(env)
    try:
        assert _status(env, job_id) == "interrupted"
        assert worker.claim() is None
    finally:
        worker.shutdown()

    job = env.jobs.get_job(job_id)
    assert job.resume_from_stage == "fundamentals"
    assert job.lease_owner is None

    events = _events(env, job_id)
    notes = [event for event in events if event.type == "reconcile_note"]
    assert len(notes) == 1
    assert notes[0].seq is None
    assert notes[0].payload == {
        "code": "unregistered_stage_output",
        "message": "发现未登记的阶段产物：新闻舆情",
        "at": "2026-10-30T09:00:00+08:00",
    }
    status_events = [
        event
        for event in _sse(env, job_id)
        if event.type == "status_changed" and event.payload["to"] == "interrupted"
    ]
    assert status_events[-1].payload == _interrupted_payload(
        "running", "unregistered_stage_output"
    )
    assert _sse(env, job_id)[-1].type == "status_changed"

    detail = _detail(env, job_id)
    assert detail["current_stage"] is None
    assert detail["reconcile_notes"] == [notes[0].payload]
    rows = _stage_rows(env, job_id)
    assert rows["market"].status == "done"
    assert rows["social"].status == "done"
    assert rows["news"].status == "active"

    resumed = _retry(env, job_id, mode="resume_from_checkpoint")
    assert resumed.status_code == 201
    resumed_id = resumed.json()["job_id"]
    assert resumed.json()["resume_from_stage"] == "fundamentals"

    outcome = _run(env)
    assert outcome.result is not None
    assert outcome.result.stages_completed == fake.STAGE_IDS[3:]
    assert _status(env, resumed_id) == "succeeded"
    started = [
        event.payload["stage_id"]
        for event in _sse(env, resumed_id)
        if event.type == "stage_changed"
        and event.payload["stage_status"] == "started"
    ]
    assert started == list(fake.STAGE_IDS[3:])


def test_cb04_b4_complete_report_is_not_imported_or_promoted(env):
    job_id = _create(env)
    _claim(env, job_id)
    env.reports.write_final_report(job_id, _golden_report(job_id))
    assert env.reports.read_final_report(job_id) is not None

    worker = _reconcile(env)
    try:
        assert _status(env, job_id) == "interrupted"
        assert worker.claim() is None
    finally:
        worker.shutdown()

    assert _report_row(env, job_id) is None
    assert env.jobs.get_job(job_id).report_id is None
    assert not any(
        event.type == "report_ready" for event in _events(env, job_id)
    )

    events = _events(env, job_id)
    notes = [event for event in events if event.type == "reconcile_note"]
    assert len(notes) == 1
    assert notes[0].seq is None
    assert notes[0].payload["code"] == "unregistered_report"
    assert notes[0].payload["message"] == "发现一份未登记的完整报告"
    assert _sse(env, job_id)[-1].payload == _interrupted_payload(
        "running", "unregistered_report"
    )
    assert _detail(env, job_id)["reconcile_notes"] == [notes[0].payload]
    assert env.reports.read_final_report(job_id) is not None


def test_cb05_b5_missing_report_ready_is_appended_at_the_tail(env):
    job_id = _create(env)
    _run(env)
    assert _status(env, job_id) == "succeeded"
    assert len(_sse(env, job_id)) == 40

    row = _report_row(env, job_id)
    assert row is not None
    expected = {
        "report_id": row.report_id,
        "content_hash": row.content_hash,
        "rating": row.rating,
        "signal": row.signal,
        "url": f"/api/v1/reports/{row.report_id}",
    }
    with Session(env.engine) as session:
        session.execute(
            delete(JobEvent).where(
                JobEvent.job_id == job_id, JobEvent.type == "report_ready"
            )
        )
        session.commit()
    assert len(_sse(env, job_id)) == 39
    before = _detail(env, job_id)

    worker = _reconcile(env)
    worker.shutdown()

    sse = _sse(env, job_id)
    assert len(sse) == 40
    assert sse[-1].type == "report_ready"
    assert sse[-1].seq == 40
    assert sse[-1].payload == expected
    assert _status(env, job_id) == "succeeded"
    assert _detail(env, job_id) == before

    again = _reconcile(env, owner="worker-startup-2")
    again.shutdown()
    assert len(_sse(env, job_id)) == 40
    assert _status(env, job_id) == "succeeded"


def test_cb06_b6_terminal_outcomes_stay_put_after_reconcile(env):
    finished_id = _create(env, ticker="000629")
    finished_executor = _TriggerAfterStage(
        lambda job: env.jobs.request_cancel(job), fake.STAGE_IDS[-1]
    )
    outcome = _run(env, finished_executor)
    assert outcome.stopped == "cancel_requested"
    assert _status(env, finished_id) == "succeeded"

    cancelled_id = _create(env, ticker="600519")
    cancelled_executor = _TriggerAfterStage(
        lambda job: env.jobs.request_cancel(job), "news"
    )
    outcome = _run(env, cancelled_executor)
    assert outcome.stopped == "cancelled"
    assert _status(env, cancelled_id) == "cancelled"

    counts = {
        job_id: len(_events(env, job_id))
        for job_id in (finished_id, cancelled_id)
    }
    worker = _reconcile(env)
    try:
        assert worker.claim() is None
    finally:
        worker.shutdown()
    assert {
        job_id: len(_events(env, job_id))
        for job_id in (finished_id, cancelled_id)
    } == counts
    assert _status(env, finished_id) == "succeeded"
    assert _status(env, cancelled_id) == "cancelled"

    finished = _sse(env, finished_id)
    order = [
        event.payload.get("detail")
        for event in finished
        if event.type == "status_changed"
    ]
    assert order[-2:] == ["cancel", "cancel_noop"]
    assert [event.type for event in finished[-2:]] == [
        "status_changed",
        "report_ready",
    ]
    assert finished[-1].seq == len(finished)

    cancelled = _sse(env, cancelled_id)
    assert [event.payload["detail"] for event in cancelled if event.type == "status_changed"][-2:] == [
        "cancel",
        "cancel",
    ]
    assert cancelled[-1].payload == {
        "from": "cancel_requested",
        "to": "cancelled",
        "reason": "worker",
        "detail": "cancel",
        "pending_action": None,
        "error": None,
    }


def test_gf21_queued_and_paused_branches(env):
    intact_id = _create(env, ticker="000629")
    _pause_job(env, intact_id)
    broken_id = _create(env, ticker="600519")
    _pause_job(env, broken_id)
    queued_id = _create(env, ticker="000001")

    shutil.rmtree(env.reports.root / broken_id)
    before_events = {
        job_id: len(_events(env, job_id))
        for job_id in (intact_id, broken_id, queued_id)
    }

    worker = _reconcile(env)
    worker.shutdown()

    assert _status(env, intact_id) == "paused"
    assert _status(env, queued_id) == "queued"
    assert _status(env, broken_id) == "interrupted"
    assert len(_events(env, intact_id)) == before_events[intact_id]
    assert len(_events(env, queued_id)) == before_events[queued_id]

    broken = _sse(env, broken_id)
    assert broken[-1].payload == _interrupted_payload(
        "paused", "checkpoint_missing"
    )
    assert env.jobs.get_job(broken_id).resume_from_stage == "fundamentals"
    assert _detail(env, intact_id)["reconcile_notes"] == []


def test_reconcile_switch_and_live_lease_skip(monkeypatch, env):
    orphan_id = _create(env)
    _claim(env, orphan_id)

    monkeypatch.setenv("TA_STARTUP_RECONCILE", "0")
    assert startup_reconcile_enabled() is False
    assert startup_reconcile_enabled({}) is True
    assert startup_reconcile_enabled({"TA_STARTUP_RECONCILE": "1"}) is True

    worker = Worker(
        env.lease(), jobs=env.jobs, reports=env.reports, owner="worker-off"
    )
    assert worker.acquire() is True
    try:
        assert _status(env, orphan_id) == "running"
    finally:
        worker.shutdown()

    monkeypatch.delenv("TA_STARTUP_RECONCILE")
    worker = _reconcile(env)
    worker.shutdown()
    assert _status(env, orphan_id) == "interrupted"

    running_id = _create(env, ticker="600519")
    lease = env.lease()
    assert lease.acquire("other-live") is True
    claimed = lease.claim_next_job("other-live")
    assert claimed is not None and claimed.id == running_id

    reconciler = Reconciler(
        env.jobs,
        env.reports,
        lease=env.lease(),
        owner="worker-startup",
        clock=env.clock,
    )
    assert reconciler.run() == []
    assert _status(env, running_id) == "running"
    assert lease.release("other-live") is True

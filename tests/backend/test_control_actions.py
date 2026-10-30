"""P1-08 acceptance tests: pause, resume and cancel at safe boundaries.

SM-05: running -> pause_requested -> paused lands at the next stage boundary;
       a repeated pause is 200 already_pending and writes no event.
SM-07: paused -> running (T09) re-attaches the idle worker and resumes from
       the checkpoint without re-executing or overwriting completed stages.
SM-08: paused -> queued (T10) when the worker is busy; the checkpoint rows,
       reports and resume_from_stage survive.
SM-09: running -> cancel_requested -> cancelled; completed stage reports stay
       readable and the cancel finishes with a final stats event (T13).
SM-10: a graph that finishes while cancel is pending ends succeeded with
       detail cancel_noop (T14); the cancel is a no-op. The completed run's
       report is committed and report_ready follows the terminal status event.
SM-11: cancel on pause_requested goes straight to cancel_requested (T12),
       never paused; a duplicate cancel is 200 already_pending.
SM-12: queued -> cancelled directly (T19) with zero calls, one zero stats
       event and no stage rows; terminal actions are rejected and audited.
SM-14: paused -> cancel_requested (T20) without returning to running, then
       T13 finishes the cancellation.

Illegal actions also write a ``transition_rejected`` audit record with seq
NULL (p1-state-machine-tests.md section 2), so the replayable stream keeps its
gapless sequence.
"""

from __future__ import annotations

import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.fake_analysis_graph as fake  # noqa: E402
from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobStage  # noqa: E402
from backend.app.services.analysis_runner import FakeAnalysisExecutor  # noqa: E402
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402

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
)
S00_STATS = {
    "model_calls": 14,
    "tokens_in": 182430,
    "tokens_out": 41208,
    "elapsed_ms": 21600000,
}


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
    client = TestClient(
        create_app(
            service=jobs,
            server_config=SERVER_CONFIG,
            report_store=reports,
        )
    )
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


def _create_job(env, ticker: str = "000629") -> str:
    outcome = env.jobs.create_job(
        {"ticker": ticker, "analysis_date": TODAY, "config": dict(CONFIG)},
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def _job(env, job_id: str) -> Job:
    with Session(env.engine) as session:
        return session.get(Job, job_id)


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
    events = [event for event in _events(env, job_id) if event.seq is not None]
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    return events


def _status_tos(events: list[JobEvent]) -> list[str]:
    return [
        event.payload["to"]
        for event in events
        if event.type == "status_changed"
    ]


def _stage_rows(env, job_id: str) -> dict[str, JobStage]:
    with Session(env.engine) as session:
        return {
            row.stage_id: row
            for row in session.scalars(
                select(JobStage).where(JobStage.job_id == job_id)
            )
        }


def _report_path(env, job_id: str, stage_id: str) -> Path:
    return env.reports.root / job_id / stage_id / "attempt-1.md"


def _report_files(env) -> list[Path]:
    return sorted(env.reports.root.rglob("*.md"))


def _action(env, job_id: str, action: str):
    return env.client.post(
        f"/api/v1/jobs/{job_id}/actions", json={"action": action}
    )


def _detail(env, job_id: str) -> dict:
    response = env.client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    return response.json()


@contextmanager
def _worker(env, *, executor=None, owner: str = "worker-test"):
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner=owner,
        executor=executor,
    )
    assert worker.acquire() is True
    try:
        yield worker
    finally:
        worker.shutdown()


class _Injector:
    """Issue a control request inside the done hook of one fake stage."""

    def __init__(self, after_stage: str, trigger) -> None:
        self._inner = FakeAnalysisExecutor()
        self._after_stage = after_stage
        self._trigger = trigger
        self._fired = False

    def run(self, request, *, on_stage=None, on_chunk=None):
        def hook(progress):
            if on_stage is not None:
                on_stage(progress)
            if (
                not self._fired
                and progress.phase == "done"
                and progress.stage_id == self._after_stage
            ):
                self._fired = True
                self._trigger()

        return self._inner.run(request, on_stage=hook, on_chunk=on_chunk)


def _run_with_trigger(env, job_id: str, after_stage: str, trigger):
    with _worker(env, executor=_Injector(after_stage, trigger)) as worker:
        return worker.run_once()


def _pause_job(env, job_id: str) -> None:
    def trigger():
        response = _action(env, job_id, "pause")
        assert response.status_code == 202
        assert response.json()["status"] == "pause_requested"

    outcome = _run_with_trigger(env, job_id, "news", trigger)
    assert outcome is not None and outcome.stopped == "paused"
    assert _job(env, job_id).status == "paused"


def _assert_stage_stats(stage_count: int) -> dict[str, int]:
    specs = fake.STAGES[:stage_count]
    return {
        "model_calls": sum(spec.model_calls for spec in specs),
        "tokens_in": sum(spec.tokens_in for spec in specs),
        "tokens_out": sum(spec.tokens_out for spec in specs),
        "elapsed_ms": sum(spec.duration_ms for spec in specs),
    }


def test_sm05_pause_lands_at_the_next_stage_boundary(env):
    job_id = _create_job(env)
    calls = []

    def trigger():
        first = _action(env, job_id, "pause")
        assert first.status_code == 202
        body = first.json()
        assert body == {
            "job_id": job_id,
            "accepted": True,
            "action": "pause",
            "accepted_at": "2026-10-30T09:00:00+08:00",
            "expected_effect": "at_stage_boundary",
            "status": "pause_requested",
        }
        again = _action(env, job_id, "pause")
        assert again.status_code == 200
        assert again.json() == {
            "job_id": job_id,
            "accepted": False,
            "reason": "already_pending",
            "status": "pause_requested",
        }
        calls.append(True)
        assert _detail(env, job_id)["allowed_actions"] == ["cancel"]

    outcome = _run_with_trigger(env, job_id, "news", trigger)
    assert calls == [True]
    assert outcome is not None
    assert outcome.stopped == "paused"
    assert outcome.result is None

    job = _job(env, job_id)
    assert job.status == "paused"
    assert job.pending_action is None
    assert job.lease_owner is None
    assert job.lease_expires_at is None
    assert job.finished_at is None
    assert job.resume_from_stage == "fundamentals"

    sse = _sse(env, job_id)
    assert len(sse) == 12
    expected = ["status_changed"]
    for _ in range(3):
        expected += ["stage_changed", "stage_changed", "stats"]
    expected += ["status_changed", "status_changed"]
    assert [event.type for event in sse] == expected

    pause_event, paused_event = sse[-2], sse[-1]
    assert pause_event.payload == {
        "from": "running",
        "to": "pause_requested",
        "reason": "user",
        "detail": "pause",
        "pending_action": "pause",
        "error": None,
    }
    assert paused_event.payload == {
        "from": "pause_requested",
        "to": "paused",
        "reason": "worker",
        "detail": "pause",
        "pending_action": None,
        "error": None,
    }

    rows = _stage_rows(env, job_id)
    assert set(rows) == set(fake.STAGE_IDS[:3])
    assert all(row.status == "done" for row in rows.values())
    assert len(_report_files(env)) == 3

    detail = _detail(env, job_id)
    assert detail["pending_action"] is None
    assert detail["current_stage"] is None
    assert detail["allowed_actions"] == ["resume", "cancel"]
    assert detail["stats"] == _assert_stage_stats(3)
    stopped_stages = [
        event.payload["stage_id"]
        for event in sse
        if event.type == "stage_changed"
    ]
    assert "fundamentals" not in stopped_stages


def test_sm07_resume_reuses_checkpoint_without_reexecuting(env):
    job_id = _create_job(env)
    _pause_job(env, job_id)
    before = {
        stage_id: _report_path(env, job_id, stage_id).read_bytes()
        for stage_id in fake.STAGE_IDS[:3]
    }

    with _worker(env) as worker:
        response = _action(env, job_id, "resume")
        assert response.status_code == 202
        assert response.json()["status"] == "running"
        job = _job(env, job_id)
        assert job.status == "running"
        assert job.pending_action is None
        assert job.resume_from_stage == "fundamentals"
        assert _detail(env, job_id)["allowed_actions"] == ["pause", "cancel"]

        outcome = worker.run_once()

    assert outcome is not None
    assert outcome.stopped is None
    assert outcome.result is not None
    assert outcome.result.stages_completed == fake.STAGE_IDS[3:]

    job = _job(env, job_id)
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.report_id == fake.report_id_for(job_id)

    rows = _stage_rows(env, job_id)
    assert set(rows) == set(fake.STAGE_IDS)
    assert all(row.status == "done" for row in rows.values())
    for stage_id, content in before.items():
        assert _report_path(env, job_id, stage_id).read_bytes() == content
    assert len(_report_files(env)) == 12

    sse = _sse(env, job_id)
    assert len(sse) == 43
    assert _status_tos(sse) == [
        "running",
        "pause_requested",
        "paused",
        "running",
        "succeeded",
    ]
    resume_event = [
        event
        for event in sse
        if event.type == "status_changed" and event.payload["to"] == "running"
    ][-1]
    assert resume_event.payload["from"] == "paused"
    assert resume_event.payload["detail"] == "resume"
    assert resume_event.payload["reason"] == "user"

    started = [
        event.payload["stage_id"]
        for event in sse
        if event.type == "stage_changed"
        and event.payload["stage_status"] == "started"
    ]
    assert started == list(fake.STAGE_IDS)

    stats = [event for event in sse if event.type == "stats"]
    assert len(stats) == 13
    assert stats[-1].payload == S00_STATS
    ready = [event for event in sse if event.type == "report_ready"]
    assert len(ready) == 1
    assert ready[0].payload["report_id"] == fake.report_id_for(job_id)


def test_sm08_busy_worker_resume_queues_and_keeps_checkpoint(env):
    job_id = _create_job(env)
    _pause_job(env, job_id)
    other_id = _create_job(env, ticker="600519")
    before = {
        stage_id: _report_path(env, job_id, stage_id).read_bytes()
        for stage_id in fake.STAGE_IDS[:3]
    }

    with _worker(env) as worker:
        claimed = worker.claim()
        assert claimed is not None and claimed.id == other_id

        response = _action(env, job_id, "resume")
        assert response.status_code == 202
        assert response.json()["status"] == "queued"

        job = _job(env, job_id)
        assert job.status == "queued"
        assert job.pending_action is None
        assert job.resume_from_stage == "fundamentals"
        assert job.lease_owner is None

        rows = _stage_rows(env, job_id)
        assert set(rows) == set(fake.STAGE_IDS[:3])
        assert all(row.status == "done" for row in rows.values())
        for stage_id, content in before.items():
            assert _report_path(env, job_id, stage_id).read_bytes() == content

        assert _detail(env, job_id)["allowed_actions"] == ["cancel"]

    sse = _sse(env, job_id)
    assert sse[-1].type == "status_changed"
    assert sse[-1].payload == {
        "from": "paused",
        "to": "queued",
        "reason": "user",
        "detail": "resume",
        "pending_action": None,
        "error": None,
    }


def test_sm09_cancel_running_finishes_at_boundary_and_keeps_reports(env):
    job_id = _create_job(env)

    def trigger():
        response = _action(env, job_id, "cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancel_requested"
        assert _detail(env, job_id)["allowed_actions"] == []

    outcome = _run_with_trigger(env, job_id, "news", trigger)
    assert outcome is not None
    assert outcome.stopped == "cancelled"

    job = _job(env, job_id)
    assert job.status == "cancelled"
    assert job.pending_action is None
    assert job.finished_at == "2026-10-30T09:00:00+08:00"
    assert job.report_id is None
    assert job.lease_owner is None

    sse = _sse(env, job_id)
    assert len(sse) == 13
    assert _status_tos(sse) == ["running", "cancel_requested", "cancelled"]
    assert sse[-2].type == "stats"
    assert sse[-2].payload == _assert_stage_stats(3)
    assert sse[-1].payload == {
        "from": "cancel_requested",
        "to": "cancelled",
        "reason": "worker",
        "detail": "cancel",
        "pending_action": None,
        "error": None,
    }
    assert not any(event.type == "report_ready" for event in sse)

    rows = _stage_rows(env, job_id)
    assert set(rows) == set(fake.STAGE_IDS[:3])
    assert len(_report_files(env)) == 3
    for stage_id in fake.STAGE_IDS[:3]:
        report = env.reports.read_stage_report(
            f"{job_id}/{stage_id}/attempt-1.md"
        )
        assert report is not None and report.truncated is False

    detail = _detail(env, job_id)
    assert detail["allowed_actions"] == ["reanalyze"]
    assert detail["current_stage"] is None


def test_sm10_cancel_late_ends_succeeded_with_cancel_noop(env):
    job_id = _create_job(env)

    def trigger():
        response = _action(env, job_id, "cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancel_requested"

    outcome = _run_with_trigger(env, job_id, "pm", trigger)
    assert outcome is not None
    assert outcome.stopped == "cancel_requested"
    assert outcome.result is not None

    job = _job(env, job_id)
    assert job.status == "succeeded"
    assert job.pending_action is None
    assert job.finished_at == "2026-10-30T09:00:00+08:00"
    assert job.report_id == fake.report_id_for(job_id)

    sse = _sse(env, job_id)
    assert len(sse) == 41
    assert _status_tos(sse) == ["running", "cancel_requested", "succeeded"]
    assert sse[-3].type == "stats"
    assert sse[-3].payload == S00_STATS
    assert sse[-2].payload == {
        "from": "cancel_requested",
        "to": "succeeded",
        "reason": "worker",
        "detail": "cancel_noop",
        "pending_action": None,
        "error": None,
    }
    assert sse[-1].type == "report_ready"
    assert sse[-1].payload["report_id"] == fake.report_id_for(job_id)
    assert sse[-1].payload["url"] == f"/api/v1/reports/{fake.report_id_for(job_id)}"

    rows = _stage_rows(env, job_id)
    assert len(rows) == 12 and all(row.status == "done" for row in rows.values())
    assert len(_report_files(env)) == 12
    detail = _detail(env, job_id)
    assert detail["allowed_actions"] == ["retry", "reanalyze"]


def test_sm11_cancel_wins_over_a_pause_request(env):
    job_id = _create_job(env)

    def trigger():
        pause = _action(env, job_id, "pause")
        assert pause.status_code == 202
        cancel = _action(env, job_id, "cancel")
        assert cancel.status_code == 202
        assert cancel.json()["status"] == "cancel_requested"
        again = _action(env, job_id, "cancel")
        assert again.status_code == 200
        assert again.json()["reason"] == "already_pending"
        assert _job(env, job_id).status == "cancel_requested"
        assert _detail(env, job_id)["allowed_actions"] == []

    outcome = _run_with_trigger(env, job_id, "news", trigger)
    assert outcome is not None
    assert outcome.stopped == "cancelled"

    job = _job(env, job_id)
    assert job.status == "cancelled"
    assert job.pending_action is None

    sse = _sse(env, job_id)
    assert len(sse) == 14
    tos = _status_tos(sse)
    assert tos == ["running", "pause_requested", "cancel_requested", "cancelled"]
    assert "paused" not in tos
    assert len([event for event in sse if event.type == "stats"]) == 4
    assert _detail(env, job_id)["allowed_actions"] == ["reanalyze"]


def test_sm12_queued_cancel_is_direct_and_uses_no_worker(env):
    job_id = _create_job(env)

    response = _action(env, job_id, "cancel")
    assert response.status_code == 202
    assert response.json() == {
        "job_id": job_id,
        "accepted": True,
        "action": "cancel",
        "accepted_at": "2026-10-30T09:00:00+08:00",
        "expected_effect": "at_stage_boundary",
        "status": "cancelled",
    }

    job = _job(env, job_id)
    assert job.status == "cancelled"
    assert job.pending_action is None
    assert job.started_at is None
    assert job.finished_at == "2026-10-30T09:00:00+08:00"
    assert job.report_id is None

    sse = _sse(env, job_id)
    assert len(sse) == 2
    assert sse[0].type == "stats"
    assert sse[0].payload == {
        "model_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "elapsed_ms": 0,
    }
    assert sse[1].payload == {
        "from": "queued",
        "to": "cancelled",
        "reason": "user",
        "detail": "cancel",
        "pending_action": None,
        "error": None,
    }
    assert _stage_rows(env, job_id) == {}
    assert _report_files(env) == []

    with _worker(env) as worker:
        assert worker.run_once() is None
    assert _job(env, job_id).status == "cancelled"

    detail = _detail(env, job_id)
    assert detail["allowed_actions"] == ["reanalyze"]
    assert detail["current_stage"] is None
    assert detail["stats"] == {
        "model_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "elapsed_ms": 0,
    }

    rejected = _action(env, job_id, "cancel")
    assert rejected.status_code == 409
    error = rejected.json()["error"]
    assert error["code"] == "illegal_transition"
    assert error["details"] == {
        "from": "cancelled",
        "action": "cancel",
        "rule": None,
    }
    audits = [
        event for event in _events(env, job_id)
        if event.type == "transition_rejected"
    ]
    assert len(audits) == 1
    assert audits[0].seq is None
    assert audits[0].payload["reason"] == "illegal_transition"
    assert len(_sse(env, job_id)) == 2


def test_sm14_paused_cancel_goes_through_cancel_requested(env):
    job_id = _create_job(env)
    _pause_job(env, job_id)

    # The worker stays up for the request: startup reconcile would treat an
    # orphan cancel_requested row as a crashed worker (T16-T18 -> interrupted),
    # but a live worker must honour T20 and finish the cancel itself.
    with _worker(env) as worker:
        response = _action(env, job_id, "cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancel_requested"

        job = _job(env, job_id)
        assert job.status == "cancel_requested"
        assert job.pending_action == "cancel"
        assert job.finished_at is None
        assert _detail(env, job_id)["allowed_actions"] == []

        outcome = worker.run_once()

    assert outcome is not None
    assert outcome.stopped == "cancelled"
    job = _job(env, job_id)
    assert job.status == "cancelled"
    assert job.pending_action is None
    assert job.finished_at == "2026-10-30T09:00:00+08:00"

    sse = _sse(env, job_id)
    assert len(sse) == 15
    assert _status_tos(sse) == [
        "running",
        "pause_requested",
        "paused",
        "cancel_requested",
        "cancelled",
    ]
    assert sse[-2].type == "stats"
    assert sse[-2].payload == _assert_stage_stats(3)
    assert len(_report_files(env)) == 3
    assert _detail(env, job_id)["allowed_actions"] == ["reanalyze"]


def test_illegal_control_actions_are_rejected_and_audited(env):
    job_id = _create_job(env)

    pause = _action(env, job_id, "pause")
    assert pause.status_code == 409
    assert pause.json()["error"] == {
        "code": "illegal_transition",
        "message": "当前状态不支持这个操作",
        "request_id": pause.headers["X-Request-Id"],
        "details": {"from": "queued", "action": "pause", "rule": "I06"},
    }

    resume = _action(env, job_id, "resume")
    assert resume.status_code == 409
    assert resume.json()["error"]["details"] == {
        "from": "queued",
        "action": "resume",
        "rule": None,
    }

    assert _job(env, job_id).status == "queued"
    assert _sse(env, job_id) == []
    audits = [
        event for event in _events(env, job_id)
        if event.type == "transition_rejected"
    ]
    assert len(audits) == 2
    assert all(event.seq is None for event in audits)
    assert [audit.payload["rule"] for audit in audits] == ["I06", None]

    bad_action = env.client.post(
        f"/api/v1/jobs/{job_id}/actions", json={"action": "stop"}
    )
    assert bad_action.status_code == 400
    assert bad_action.json()["error"]["code"] == "invalid_request"
    assert bad_action.json()["error"]["details"] == {"field": "action"}

    missing = env.client.post("/api/v1/jobs/does-not-exist/actions", json={"action": "cancel"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"

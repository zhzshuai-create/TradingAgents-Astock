"""P1-09 acceptance tests: terminal writes and retry/resume.

SM-03: running -> succeeded commits one report row whose content_hash is the
       canonical hash of the sections, and report_ready is appended once.
SM-04: running -> failed records the error code/text on the job and in the
       terminal event; the still-active stage becomes failed (stage_failed),
       while an exception between stages is post_stage_error.
SM-07 / SM-10 / SM-12: succeeded (normal and late-cancel no-op) and cancelled
       rows refuse a second terminal write; a late cancel cannot land after
       T14 succeeded (B6).
RT-01: retry returns a new job id and points retry_of_job_id at the original.
RT-02: the original job's status, report and events are untouched by retry.
Resume: resume_from_checkpoint is interrupted-only, starts at the first
       unfinished stage and rejects a changed fingerprint.

ID-09 (PDF cache hit must not re-render) is deferred to P3: the PDF export
endpoint and renderer are P3 scope, so P1-09 does not pre-build them.
"""

from __future__ import annotations

import copy
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
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
from backend.app.services.analysis_runner import StageProgress  # noqa: E402
from backend.app.services.job_service import (  # noqa: E402
    CST,
    JobService,
    StatsSnapshot,
)
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_document import (  # noqa: E402
    compute_content_hash,
    finalize_report,
)
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402

BACKEND = ROOT / "backend"
CLOCK = datetime(2026, 10, 30, 9, 0, tzinfo=CST)
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
S00_STATS = StatsSnapshot(
    model_calls=14,
    tokens_in=182430,
    tokens_out=41208,
    elapsed_ms=21600000,
)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    command.upgrade(_alembic_config(), "head")

    clock = lambda: CLOCK  # noqa: E731
    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    service = JobService(engine, SERVER_CONFIG, clock=clock, reports=reports)
    app = create_app(
        service=service, server_config=SERVER_CONFIG, report_store=reports
    )
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            engine=engine,
            service=service,
            reports=reports,
            client=client,
            lease=lambda **kwargs: LeaseService(engine, clock=clock, **kwargs),
        )
    finally:
        client.close()
        engine.dispose()


def _body(ticker: str = "000629") -> dict:
    return {
        "ticker": ticker,
        "analysis_date": TODAY,
        "config": copy.deepcopy(CONFIG),
    }


def _create(env, ticker: str = "000629") -> str:
    response = env.client.post(
        "/api/v1/jobs",
        json=_body(ticker),
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201
    return response.json()["job_id"]


def _retry(
    env,
    job_id: str,
    *,
    mode: str = "same_config",
    key: str | None = None,
):
    return env.client.post(
        f"/api/v1/jobs/{job_id}/retry",
        json={"mode": mode},
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


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


def _event_snapshot(env, job_id: str) -> list[tuple]:
    return [
        (event.seq, event.type, copy.deepcopy(event.payload), event.created_at)
        for event in _events(env, job_id)
    ]


def _job_count(env) -> int:
    with Session(env.engine) as session:
        return session.scalar(select(func.count()).select_from(Job))


def _report_row(env, job_id: str) -> Report | None:
    with Session(env.engine) as session:
        return session.scalars(
            select(Report).where(Report.job_id == job_id)
        ).first()


def _report_counts(env) -> tuple[int, int, int]:
    with Session(env.engine) as session:
        return (
            session.scalar(select(func.count()).select_from(Report)),
            session.scalar(
                select(func.count())
                .select_from(JobEvent)
                .where(JobEvent.type == "report_ready")
            ),
            session.scalar(select(func.count()).select_from(JobEvent)),
        )


def _run(env, executor=None) -> SimpleNamespace:
    worker = Worker(
        env.lease(),
        jobs=env.service,
        reports=env.reports,
        owner="worker-test",
        executor=executor,
    )
    assert worker.acquire() is True
    try:
        outcome = worker.run_once()
        assert outcome is not None
        return outcome
    finally:
        worker.shutdown()


def _golden_report(job_id: str) -> dict:
    graph = fake.FakeAnalysisGraph("000629", TODAY)
    return graph.build_report(job_id, generated_at=CLOCK)


class _Boom(Exception):
    def __init__(
        self, code: str = "upstream_timeout", message: str = "数据源响应超时"
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _FailingExecutor:
    """Raises on a chosen stage; ``fail_at=None`` raises after all twelve."""

    name = "failing"

    def __init__(
        self,
        *,
        fail_at: str | None,
        code: str = "upstream_timeout",
        message: str = "数据源响应超时",
    ) -> None:
        self.fail_at = fail_at
        self.code = code
        self.message = message

    def run(self, request, *, on_stage=None, on_chunk=None):
        total = len(fake.STAGES)
        for index, spec in enumerate(fake.STAGES, 1):
            if spec.id == self.fail_at:
                assert on_stage is not None
                on_stage(
                    StageProgress(
                        stage_id=spec.id,
                        stage_name=spec.name,
                        phase="started",
                        index=index,
                        total=total,
                    )
                )
                raise _Boom(self.code, self.message)
            assert on_stage is not None
            on_stage(
                StageProgress(
                    stage_id=spec.id,
                    stage_name=spec.name,
                    phase="started",
                    index=index,
                    total=total,
                )
            )
            on_stage(
                StageProgress(
                    stage_id=spec.id,
                    stage_name=spec.name,
                    phase="done",
                    index=index,
                    total=total,
                    report_text=f"{spec.name}报告",
                    model_calls=spec.model_calls,
                    tokens_in=spec.tokens_in,
                    tokens_out=spec.tokens_out,
                    duration_ms=spec.duration_ms,
                )
            )
        raise _Boom(self.code, self.message)


class _ControlThenFailExecutor:
    """Starts a stage, records pause/cancel, then raises (T08/T15)."""

    name = "control-then-fail"

    def __init__(self, service: JobService, action: str, fail_at: str) -> None:
        self._service = service
        self._action = action
        self._fail_at = fail_at

    def run(self, request, *, on_stage=None, on_chunk=None):
        total = len(fake.STAGES)
        for index, spec in enumerate(fake.STAGES, 1):
            assert on_stage is not None
            if spec.id == self._fail_at:
                on_stage(
                    StageProgress(
                        stage_id=spec.id,
                        stage_name=spec.name,
                        phase="started",
                        index=index,
                        total=total,
                    )
                )
                if self._action == "pause":
                    self._service.request_pause(request.job_id)
                else:
                    self._service.request_cancel(request.job_id)
                raise _Boom("graph_crashed", "执行器在收尾期间崩溃")
            on_stage(
                StageProgress(
                    stage_id=spec.id,
                    stage_name=spec.name,
                    phase="started",
                    index=index,
                    total=total,
                )
            )
            on_stage(
                StageProgress(
                    stage_id=spec.id,
                    stage_name=spec.name,
                    phase="done",
                    index=index,
                    total=total,
                    report_text=f"{spec.name}报告",
                    duration_ms=spec.duration_ms,
                )
            )
        raise AssertionError("stage not reached")


def _claim(env, job_id: str, owner: str = "worker-test") -> None:
    lease = env.lease()
    assert lease.acquire(owner) is True
    claimed = lease.claim_next_job(owner)
    assert claimed is not None and claimed.id == job_id
    # The job lease is what the terminal write releases; the global lease is
    # only needed for the claim itself.
    assert lease.release(owner) is True


def _interrupt(env, job_id: str) -> None:
    with Session(env.engine) as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="interrupted",
                finished_at=CLOCK.isoformat(timespec="seconds"),
                updated_at=CLOCK.isoformat(timespec="seconds"),
            )
        )
        session.commit()


def _mark_stages_done(env, job_id: str, count: int) -> None:
    with Session(env.engine) as session:
        for spec in fake.STAGES[:count]:
            session.add(
                JobStage(
                    job_id=job_id,
                    stage_id=spec.id,
                    status="done",
                    started_at=CLOCK.isoformat(timespec="seconds"),
                    ended_at=CLOCK.isoformat(timespec="seconds"),
                )
            )
        session.commit()


def test_report_finalization_is_server_authoritative():
    sections = {"sec-decision": {"title": "最终交易决策", "body": "观察"}}
    raw = {
        "meta": {
            "report_id": "0f1e2d3c-4b5a-6978-8765-4321fedcba98",
            "job_id": "someone-else",
            "ticker_code": "999999",
            "analysis_date": "2026-01-01",
            "generated_at": "2020-01-01T00:00:00+08:00",
            "config_digest": "stale",
            "rating": "Sell",
            "signal": "Buy",
            "content_hash": "0" * 64,
            "data_quality_status": "bogus",
            "chart_snapshot_status": "bogus",
            "retry_of_job_id": "wrong",
        },
        "sections": sections,
    }

    payload = finalize_report(
        raw,
        job_id="job-new",
        ticker_code="000629",
        ticker_name="攀钢钒钛",
        analysis_date="2026-10-30",
        generated_at="2026-10-30T09:00:00+08:00",
        config_digest="cfg-job",
        retry_of_job_id=None,
    )

    meta = payload["meta"]
    assert meta["job_id"] == "job-new"
    assert meta["ticker_code"] == "000629"
    assert meta["analysis_date"] == "2026-10-30"
    assert meta["generated_at"] == "2026-10-30T09:00:00+08:00"
    assert meta["config_digest"] == "cfg-job"
    assert meta["retry_of_job_id"] is None
    assert meta["rating"] == "Sell"
    assert meta["signal"] == "Sell"
    assert meta["content_hash"] == compute_content_hash(sections)
    assert meta["data_quality_status"] == "absent"
    assert meta["chart_snapshot_status"] == "none"
    assert raw["meta"]["job_id"] == "someone-else"
    assert raw["meta"]["content_hash"] == "0" * 64


def test_sm03_success_commits_one_report_and_one_report_ready(env):
    job_id = _create(env)
    outcome = _run(env)
    assert outcome.result is not None

    detail = _detail(env, job_id)
    assert detail["status"] == "succeeded"
    assert detail["error"] is None
    assert detail["allowed_actions"] == ["retry", "reanalyze"]
    assert detail["finished_at"] == CLOCK.isoformat(timespec="seconds")
    assert detail["report_id"] == fake.report_id_for(job_id)
    assert detail["links"]["report"] == (
        f"/api/v1/reports/{fake.report_id_for(job_id)}"
    )

    golden = fake.load_golden_report()
    row = _report_row(env, job_id)
    assert row is not None
    assert row.job_id == job_id
    assert row.content_hash == golden["meta"]["content_hash"]
    assert row.content_hash == fake.compute_content_hash(row.payload["sections"])
    assert row.rating == golden["meta"]["rating"]
    assert row.signal == golden["meta"]["signal"]
    assert row.payload["meta"]["job_id"] == job_id
    assert row.payload["meta"]["content_hash"] == row.content_hash
    assert row.payload["meta"]["generated_at"] == (
        CLOCK.isoformat(timespec="seconds")
    )
    assert row.payload["meta"]["config_digest"] == detail["config_digest"]

    sse = _sse(env, job_id)
    assert [event.type for event in sse[-3:]] == [
        "stats",
        "status_changed",
        "report_ready",
    ]
    assert sse[-3].payload == S00_STATS.as_payload()
    assert sse[-2].payload == {
        "from": "running",
        "to": "succeeded",
        "reason": "worker",
        "detail": None,
        "pending_action": None,
        "error": None,
    }
    assert sse[-1].payload == {
        "report_id": row.report_id,
        "content_hash": row.content_hash,
        "rating": row.rating,
        "signal": row.signal,
        "url": f"/api/v1/reports/{row.report_id}",
    }

    before = _report_counts(env)
    assert (
        env.service.finish_success(
            job_id,
            detail=None,
            stats=StatsSnapshot(),
            report=_golden_report(job_id),
        )
        is False
    )
    assert _report_counts(env) == before
    assert _detail(env, job_id) == detail


def test_sm04_stage_failure_marks_the_active_stage_and_error(env):
    job_id = _create(env)
    outcome = _run(env, _FailingExecutor(fail_at="news"))
    assert outcome.stopped == "failed"

    detail = _detail(env, job_id)
    assert detail["status"] == "failed"
    assert detail["error"] == {
        "code": "upstream_timeout",
        "message": "数据源响应超时",
    }
    assert detail["report_id"] is None
    assert detail["allowed_actions"] == ["retry", "reanalyze"]

    stages = {stage["id"]: stage for stage in detail["stages"]}
    assert stages["market"]["status"] == "done"
    assert stages["social"]["status"] == "done"
    assert stages["news"]["status"] == "failed"
    assert stages["news"]["finished_at"] is not None
    assert stages["fundamentals"]["status"] == "pending"

    with Session(env.engine) as session:
        job = session.get(Job, job_id)
        assert job.error_code == "upstream_timeout"
        assert job.error_message == "数据源响应超时"
        rows = {
            row.stage_id: row.status
            for row in session.scalars(
                select(JobStage).where(JobStage.job_id == job_id)
            )
        }
    assert rows == {"market": "done", "social": "done", "news": "failed"}

    sse = _sse(env, job_id)
    assert sse[-3].type == "stage_changed"
    assert sse[-3].payload["stage_id"] == "news"
    assert sse[-3].payload["stage_status"] == "failed"
    assert sse[-2].type == "stats"
    assert sse[-1].payload == {
        "from": "running",
        "to": "failed",
        "reason": "worker",
        "detail": "stage_failed",
        "pending_action": None,
        "error": {
            "code": "upstream_timeout",
            "message": "数据源响应超时",
        },
    }
    assert not any(event.type == "report_ready" for event in sse)
    assert _report_row(env, job_id) is None

    before = _event_snapshot(env, job_id)
    assert (
        env.service.finish_failure(
            job_id,
            code="internal_error",
            message="分析执行失败",
            stats=StatsSnapshot(),
        )
        is False
    )
    assert _event_snapshot(env, job_id) == before


def test_sm04_post_stage_error_has_no_failed_stage(env):
    job_id = _create(env)
    outcome = _run(
        env,
        _FailingExecutor(
            fail_at=None, code="internal_error", message="分析执行失败"
        ),
    )
    assert outcome.stopped == "failed"

    detail = _detail(env, job_id)
    assert detail["status"] == "failed"
    assert detail["error"] == {
        "code": "internal_error",
        "message": "分析执行失败",
    }
    assert {stage["status"] for stage in detail["stages"]} == {"done"}
    sse = _sse(env, job_id)
    assert sse[-2].type == "stats"
    assert sse[-1].payload["detail"] == "post_stage_error"
    assert sse[-1].payload["error"] == {
        "code": "internal_error",
        "message": "分析执行失败",
    }


def test_sm04_failure_logs_the_exception_traceback(env, caplog):
    job_id = _create(env)
    with caplog.at_level(logging.ERROR, logger="backend.app.worker.main"):
        outcome = _run(
            env,
            _FailingExecutor(
                fail_at="news", code="internal_error", message="分析执行失败"
            ),
        )
    assert outcome.stopped == "failed"

    assert "analysis failed for job" in caplog.text
    assert job_id in caplog.text
    assert "Traceback" in caplog.text
    assert "_Boom" in caplog.text
    # 栈只进服务端日志；API 与数据库仍只有用户可读文本。
    assert _detail(env, job_id)["error"] == {
        "code": "internal_error",
        "message": "分析执行失败",
    }


def test_t08_t15_failure_while_a_control_is_pending(env):
    cases = (("pause", "pause_requested"), ("cancel", "cancel_requested"))
    for action, pending_status in cases:
        job_id = _create(env, ticker="600519" if action == "pause" else "000001")
        executor = _ControlThenFailExecutor(env.service, action, "news")
        outcome = _run(env, executor)
        assert outcome.stopped == "failed"
        assert (
            env.service.get_job(job_id).status == "failed"
        ), f"{action} left a non-terminal row"

        detail = _detail(env, job_id)
        assert detail["status"] == "failed"
        assert detail["pending_action"] is None
        assert detail["error"] == {
            "code": "graph_crashed",
            "message": "执行器在收尾期间崩溃",
        }
        stages = {stage["id"]: stage for stage in detail["stages"]}
        assert stages["news"]["status"] == "failed"

        sse = _sse(env, job_id)
        assert sse[-2].type == "stats"
        assert sse[-1].payload["from"] == pending_status
        assert sse[-1].payload["to"] == "failed"
        assert sse[-1].payload["detail"] == "stage_failed"
        assert sse[-1].payload["pending_action"] is None
        assert sse[-1].payload["error"] == {
            "code": "graph_crashed",
            "message": "执行器在收尾期间崩溃",
        }


def test_sm07_sm10_sm12_terminal_writes_happen_once(env):
    succeeded_id = _create(env)
    _claim(env, succeeded_id)
    assert env.service.finish_success(
        succeeded_id,
        detail=None,
        stats=S00_STATS,
        report=_golden_report(succeeded_id),
    )
    assert env.service.get_job(succeeded_id).status == "succeeded"

    late_cancel_id = _create(env, ticker="600519")
    _claim(env, late_cancel_id)
    assert env.service.request_cancel(late_cancel_id).accepted is True
    assert env.service.finish_success(
        late_cancel_id,
        detail="cancel_noop",
        stats=S00_STATS,
        report=_golden_report(late_cancel_id),
    )
    assert env.service.get_job(late_cancel_id).status == "succeeded"
    # B6: T13 cannot land after T14 committed.
    assert env.service.cancel_at_boundary(late_cancel_id) is False
    late_sse = _sse(env, late_cancel_id)
    assert late_sse[-1].type == "report_ready"
    assert late_sse[-2].payload["detail"] == "cancel_noop"

    cancelled_id = _create(env, ticker="000001")
    assert env.service.request_cancel(cancelled_id).accepted is True
    assert env.service.get_job(cancelled_id).status == "cancelled"

    before = _report_counts(env)
    before_cancelled = _event_snapshot(env, cancelled_id)
    for job_id in (succeeded_id, late_cancel_id, cancelled_id):
        assert (
            env.service.finish_success(
                job_id,
                detail=None,
                stats=StatsSnapshot(),
                report=None,
            )
            is False
        )
        assert (
            env.service.finish_failure(
                job_id,
                code="internal_error",
                message="分析执行失败",
                stats=StatsSnapshot(),
            )
            is False
        )
    assert _report_counts(env) == before
    assert _event_snapshot(env, cancelled_id) == before_cancelled
    assert env.service.get_job(cancelled_id).status == "cancelled"


def test_rt01_rt02_retry_creates_a_new_job_and_leaves_the_original(env):
    job_id = _create(env)
    _run(env)
    assert _detail(env, job_id)["status"] == "succeeded"

    original_detail = _detail(env, job_id)
    original_events = _event_snapshot(env, job_id)
    original_report = _report_row(env, job_id)
    assert original_report is not None
    original_report_state = (
        original_report.report_id,
        original_report.content_hash,
        copy.deepcopy(original_report.payload),
        original_report.created_at,
    )
    key = str(uuid.uuid4())

    response = _retry(env, job_id, key=key)
    assert response.status_code == 201
    retried = response.json()
    assert retried["job_id"] != job_id
    assert retried["retry_of_job_id"] == job_id
    assert retried["resume_of_job_id"] is None
    assert retried["resume_from_stage"] is None
    assert retried["status"] == "queued"
    assert retried["config_digest"] == original_detail["config_digest"]
    assert retried["allowed_actions"] == ["cancel"]
    assert {stage["status"] for stage in retried["stages"]} == {"pending"}

    assert _detail(env, job_id) == original_detail
    assert _event_snapshot(env, job_id) == original_events
    report_after = _report_row(env, job_id)
    assert report_after is not None
    assert (
        report_after.report_id,
        report_after.content_hash,
        copy.deepcopy(report_after.payload),
        report_after.created_at,
    ) == original_report_state
    assert _job_count(env) == 2

    replay = _retry(env, job_id, key=key)
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "1"
    assert replay.json()["job_id"] == retried["job_id"]
    assert _job_count(env) == 2

    mismatch = _retry(
        env, job_id, mode="resume_from_checkpoint", key=key
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "idempotency_mismatch"

    step_three = _retry(env, job_id)
    assert step_three.status_code == 200
    assert step_three.headers["X-Existing-Job"] == retried["job_id"]
    assert _job_count(env) == 2

    missing_key = env.client.post(
        f"/api/v1/jobs/{job_id}/retry", json={"mode": "same_config"}
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "idempotency_key_required"


def test_retry_after_failure_runs_a_report_linked_to_the_original(env):
    job_id = _create(env)
    _run(env, _FailingExecutor(fail_at="news"))
    assert _detail(env, job_id)["status"] == "failed"
    original_events = _event_snapshot(env, job_id)

    response = _retry(env, job_id)
    assert response.status_code == 201
    retried_id = response.json()["job_id"]

    _run(env)
    detail = _detail(env, retried_id)
    assert detail["status"] == "succeeded"
    assert detail["retry_of_job_id"] == job_id
    row = _report_row(env, retried_id)
    assert row is not None
    assert row.retry_of_job_id == job_id
    assert row.payload["meta"]["retry_of_job_id"] == job_id
    assert row.payload["meta"]["job_id"] == retried_id
    assert _event_snapshot(env, job_id) == original_events


def test_retry_rejects_states_outside_the_contract(env):
    job_id = _create(env)

    queued = _retry(env, job_id)
    assert queued.status_code == 409
    assert queued.json()["error"] == {
        "code": "illegal_transition",
        "message": "当前状态不支持这个操作",
        "request_id": queued.headers["X-Request-Id"],
        "details": {"from": "queued", "action": "retry", "rule": None},
    }

    assert (
        env.client.post(
            f"/api/v1/jobs/{job_id}/actions",
            json={"action": "cancel"},
        ).status_code
        == 202
    )
    cancelled = _retry(env, job_id)
    assert cancelled.status_code == 409
    assert cancelled.json()["error"]["details"] == {
        "from": "cancelled",
        "action": "retry",
        "rule": None,
    }

    missing = _retry(env, str(uuid.uuid4()))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"

    invalid_mode = env.client.post(
        f"/api/v1/jobs/{job_id}/retry",
        json={"mode": "reanalyze"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert invalid_mode.status_code == 400
    assert invalid_mode.json()["error"]["code"] == "invalid_request"
    assert invalid_mode.json()["error"]["details"] == {"field": "mode"}

    extra = env.client.post(
        f"/api/v1/jobs/{job_id}/retry",
        json={"mode": "same_config", "unexpected": 1},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert extra.status_code == 422
    assert extra.json()["error"]["details"] == {"field": "unexpected"}


def test_resume_from_checkpoint_starts_at_the_first_unfinished_stage(env):
    job_id = _create(env)
    _interrupt(env, job_id)
    _mark_stages_done(env, job_id, 3)

    response = _retry(env, job_id, mode="resume_from_checkpoint")
    assert response.status_code == 201
    resumed = response.json()
    assert resumed["resume_of_job_id"] == job_id
    assert resumed["retry_of_job_id"] is None
    assert resumed["resume_from_stage"] == "fundamentals"
    assert resumed["status"] == "queued"
    assert _detail(env, job_id)["status"] == "interrupted"


def test_resume_requires_interrupted_and_a_matching_fingerprint(env):
    succeeded_id = _create(env)
    _run(env)
    assert _detail(env, succeeded_id)["status"] == "succeeded"
    wrong_state = _retry(
        env, succeeded_id, mode="resume_from_checkpoint"
    )
    assert wrong_state.status_code == 409
    assert wrong_state.json()["error"]["details"] == {
        "from": "succeeded",
        "action": "resume_from_checkpoint",
        "rule": None,
    }

    changed_config = _create(env, ticker="600519")
    _interrupt(env, changed_config)
    with Session(env.engine) as session:
        session.execute(
            update(Job)
            .where(Job.id == changed_config)
            .values(config_hash="0" * 64)
        )
        session.commit()
    mismatch = _retry(env, changed_config, mode="resume_from_checkpoint")
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "resume_fingerprint_mismatch"
    assert mismatch.json()["error"]["details"] == {"field": "config_digest"}

    changed_graph = _create(env, ticker="000001")
    _interrupt(env, changed_graph)
    with Session(env.engine) as session:
        session.execute(
            update(Job)
            .where(Job.id == changed_graph)
            .values(graph_version="graph-v0")
        )
        session.commit()
    graph_mismatch = _retry(
        env, changed_graph, mode="resume_from_checkpoint"
    )
    assert graph_mismatch.status_code == 409
    assert (
        graph_mismatch.json()["error"]["code"]
        == "resume_fingerprint_mismatch"
    )

    same_config = _retry(env, changed_graph)
    assert same_config.status_code == 201
    assert same_config.json()["retry_of_job_id"] == changed_graph
    assert same_config.json()["resume_of_job_id"] is None

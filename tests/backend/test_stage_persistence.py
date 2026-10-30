"""P1-07 acceptance tests: stage persistence, stats events and stage reports.

GF-03: a full fake run persists 24 stage_changed events and 13 stats events in
       a fixed order, with a gapless seq starting at the T02 claim event.
GF-13: B3 evidence (report file written, done event missing) is detected and
       recorded as a reconcile_note with seq NULL. P1-10 owns the interrupted
       transition; P1-07 only supplies detection and the audit note.
SM-03: every stage report on disk matches the fake graph output. The final
       ReportDTO row and its content hash stay in P1-09, as recorded in
       docs/upgrade/P1进度存档.md.
ST-01: stage report paths are isolated per job and stage and never overwrite a
       previous attempt.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.fake_analysis_graph as fake  # noqa: E402
from backend.app.api.v1.serializers import job_detail  # noqa: E402
from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import JobEvent, JobStage  # noqa: E402
from backend.app.services.job_service import (  # noqa: E402
    CST,
    JobService,
    StatsSnapshot,
)
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import (  # noqa: E402
    MAX_STAGE_REPORT_BYTES,
    ReportStore,
)
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
    try:
        yield SimpleNamespace(
            engine=engine,
            jobs=jobs,
            reports=reports,
            clock=clock,
            lease=lambda **kwargs: LeaseService(engine, clock=clock, **kwargs),
        )
    finally:
        engine.dispose()


def _create_job(env, ticker: str = "000629") -> str:
    outcome = env.jobs.create_job(
        {"ticker": ticker, "analysis_date": TODAY, "config": dict(CONFIG)},
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def _run_worker(env):
    worker = Worker(
        env.lease(), jobs=env.jobs, reports=env.reports, owner="worker-test"
    )
    assert worker.acquire() is True
    try:
        outcome = worker.run_once()
        assert outcome is not None
        return outcome
    finally:
        worker.shutdown()


def _claim(env, owner: str = "worker-crashed") -> None:
    lease = env.lease()
    assert lease.acquire(owner) is True
    assert lease.claim_next_job(owner) is not None


def _events(env, job_id: str) -> list[JobEvent]:
    with Session(env.engine) as session:
        return list(
            session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.id)
            )
        )


def _stage_rows(env, job_id: str) -> dict[str, JobStage]:
    with Session(env.engine) as session:
        return {
            row.stage_id: row
            for row in session.scalars(
                select(JobStage).where(JobStage.job_id == job_id)
            )
        }


def _report_files(env) -> list[str]:
    return sorted(path.as_posix() for path in env.reports.root.rglob("*.md"))


def _fake_stage_texts() -> dict[str, str]:
    graph = fake.FakeAnalysisGraph()
    init_state, args, _meta = graph.prepare_graph_run("000629", TODAY)
    try:
        return {
            spec.id: fake.extract_stage_text(chunk, spec)
            for spec, chunk in zip(fake.STAGES, graph.stream(init_state, **args))
        }
    finally:
        graph.close_graph_run()


def _cumulative_stats() -> list[dict[str, int]]:
    calls = tokens_in = tokens_out = elapsed_ms = 0
    rows: list[dict[str, int]] = []
    for spec in fake.STAGES:
        calls += spec.model_calls
        tokens_in += spec.tokens_in
        tokens_out += spec.tokens_out
        elapsed_ms += spec.duration_ms
        rows.append(
            {
                "model_calls": calls,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "elapsed_ms": elapsed_ms,
            }
        )
    return rows


def _client(env) -> TestClient:
    return TestClient(
        create_app(
            service=env.jobs,
            server_config=SERVER_CONFIG,
            report_store=env.reports,
        )
    )


def test_gf03_full_run_persists_24_stage_events_and_13_stats(env):
    job_id = _create_job(env)
    outcome = _run_worker(env)
    result = outcome.result

    events = _events(env, job_id)
    assert [event.type for event in events if event.seq is None] == ["created"]
    sse = [event for event in events if event.seq is not None]
    assert [event.seq for event in sse] == list(range(1, len(sse) + 1))
    assert len(sse) == 38

    expected_types = ["status_changed"]
    for _ in fake.STAGE_IDS:
        expected_types += ["stage_changed", "stage_changed", "stats"]
    expected_types.append("stats")
    assert [event.type for event in sse] == expected_types

    assert sse[0].payload == {
        "from": "queued",
        "to": "running",
        "reason": "worker",
        "detail": None,
        "pending_action": None,
        "error": None,
    }

    stage_events = [event for event in sse if event.type == "stage_changed"]
    assert len(stage_events) == 24
    started, done = stage_events[::2], stage_events[1::2]
    assert [event.payload["stage_id"] for event in started] == list(fake.STAGE_IDS)
    assert [event.payload["stage_id"] for event in done] == list(fake.STAGE_IDS)
    for index, (start_event, done_event) in enumerate(
        zip(started, done), start=1
    ):
        spec = fake.STAGES[index - 1]
        assert start_event.payload["stage_status"] == "started"
        assert start_event.payload["stage_name"] == spec.name
        assert start_event.payload["index"] == index
        assert start_event.payload["total"] == 12
        assert start_event.payload["started_at"] is not None
        assert start_event.payload["finished_at"] is None
        assert start_event.payload["duration_ms"] is None
        assert done_event.payload["stage_status"] == "done"
        assert done_event.payload["stage_name"] == spec.name
        assert done_event.payload["index"] == index
        assert done_event.payload["total"] == 12
        assert done_event.payload["started_at"] == start_event.payload["started_at"]
        assert done_event.payload["finished_at"] is not None
        assert done_event.payload["duration_ms"] == spec.duration_ms

    stats = [event for event in sse if event.type == "stats"]
    assert len(stats) == 13
    assert [event.payload for event in stats[:12]] == _cumulative_stats()
    assert stats[-1].payload == S00_STATS
    assert stats[-1].payload == {
        "model_calls": result.stats.model_calls,
        "tokens_in": result.stats.tokens_in,
        "tokens_out": result.stats.tokens_out,
        "elapsed_ms": result.stats.elapsed_ms,
    }

    rows = _stage_rows(env, job_id)
    assert set(rows) == set(fake.STAGE_IDS)
    for spec in fake.STAGES:
        row = rows[spec.id]
        assert row.status == "done"
        assert row.started_at is not None
        assert row.ended_at is not None
        assert row.report_path == f"{job_id}/{spec.id}/attempt-1.md"

    assert env.jobs.detect_unregistered_stage_outputs(job_id) == []
    assert env.jobs.get_job(job_id).status == "running"


def test_gf13_b3_report_written_without_done_event(env):
    job_id = _create_job(env)
    _claim(env)

    env.jobs.start_stage(job_id, "market", index=1, total=12)
    env.jobs.finish_stage(
        job_id,
        "market",
        index=1,
        total=12,
        stats=StatsSnapshot(1, 28000, 4200, 1800000),
        report_path=env.reports.write_stage_report(job_id, "market", "技术分析报告"),
        duration_ms=1800000,
    )
    env.jobs.start_stage(job_id, "social", index=2, total=12)
    env.jobs.finish_stage(
        job_id,
        "social",
        index=2,
        total=12,
        stats=StatsSnapshot(2, 50000, 9300, 3600000),
        report_path=env.reports.write_stage_report(job_id, "social", "情绪分析报告"),
        duration_ms=1800000,
    )
    env.jobs.start_stage(job_id, "news", index=3, total=12)
    news_path = env.reports.write_stage_report(job_id, "news", "新闻报告：B3")

    before_events = len(_events(env, job_id))
    before_files = _report_files(env)

    restarted = JobService(
        env.engine,
        SERVER_CONFIG,
        clock=env.clock,
        reports=ReportStore(env.reports.root),
    )
    notes = restarted.detect_unregistered_stage_outputs(job_id)

    assert [note.code for note in notes] == ["unregistered_stage_output"]
    assert notes[0].message == "发现未登记的阶段产物：新闻舆情"
    assert len(_events(env, job_id)) == before_events
    assert _report_files(env) == before_files

    recorded = restarted.record_reconcile_note(
        job_id, code=notes[0].code, message=notes[0].message
    )
    assert recorded == notes[0]
    assert recorded.at == "2026-10-30T09:00:00+08:00"

    events = _events(env, job_id)
    audit = [event for event in events if event.type == "reconcile_note"]
    assert len(audit) == 1
    assert audit[0].seq is None
    assert audit[0].payload == {
        "code": "unregistered_stage_output",
        "message": "发现未登记的阶段产物：新闻舆情",
        "at": "2026-10-30T09:00:00+08:00",
    }
    sse = [event for event in events if event.seq is not None]
    assert [event.seq for event in sse] == list(range(1, 9))
    assert len(sse) == 8

    parts = restarted.detail_parts(job_id)
    assert parts["reconcile_notes"] == [audit[0].payload]
    assert parts["stages"]["market"]["status"] == "done"
    assert parts["stages"]["news"]["status"] == "active"
    assert parts["stages"]["fundamentals"]["status"] == "pending"
    assert parts["stats"] == {
        "model_calls": 2,
        "tokens_in": 50000,
        "tokens_out": 9300,
        "elapsed_ms": 3600000,
    }

    assert restarted.get_job(job_id).status == "running"
    report = env.reports.read_stage_report(news_path)
    assert report is not None and report.markdown == "新闻报告：B3"


def test_sm03_stage_reports_match_the_fake_graph_output(env):
    expected = _fake_stage_texts()
    job_id = _create_job(env)
    result = _run_worker(env).result

    rows = _stage_rows(env, job_id)
    for spec in fake.STAGES:
        row = rows[spec.id]
        assert row.report_path == f"{job_id}/{spec.id}/attempt-1.md"
        report = env.reports.read_stage_report(row.report_path)
        assert report is not None
        assert report.markdown == expected[spec.id]
        assert report.truncated is False
        assert report.full_length == len(expected[spec.id])
        datetime.fromisoformat(report.updated_at)

    golden = fake.load_golden_report()
    assert expected["pm"] == result.last_chunk["final_trade_decision"]
    assert result.signal == golden["meta"]["signal"]
    assert all(text for text in expected.values())


def test_st01_stage_report_paths_are_isolated_and_never_overwrite(tmp_path):
    store = ReportStore(tmp_path / "store")

    first = store.write_stage_report("job-a", "news", "first attempt")
    second = store.write_stage_report("job-a", "news", "second attempt")
    other_job = store.write_stage_report("job-b", "news", "other job")
    other_stage = store.write_stage_report("job-a", "market", "other stage")

    assert first == "job-a/news/attempt-1.md"
    assert second == "job-a/news/attempt-2.md"
    assert other_job == "job-b/news/attempt-1.md"
    assert other_stage == "job-a/market/attempt-1.md"

    assert store.read_stage_report(first).markdown == "first attempt"
    assert store.read_stage_report(second).markdown == "second attempt"
    assert store.read_stage_report(other_job).markdown == "other job"
    assert store.read_stage_report(other_stage).markdown == "other stage"
    assert store.stage_report_paths("job-a") == {
        "news": second,
        "market": other_stage,
    }
    assert store.stage_report_paths("job-missing") == {}
    assert store.read_stage_report("job-a/news/attempt-3.md") is None

    with pytest.raises(ValueError):
        store.read_stage_report("../outside.md")
    with pytest.raises(ValueError):
        store.write_stage_report("..", "news", "escape")
    with pytest.raises(ValueError):
        store.write_stage_report("job-a", "news/../market", "escape")


def test_stage_report_read_truncates_at_128_kib(tmp_path):
    store = ReportStore(tmp_path / "store")

    ascii_text = "x" * (MAX_STAGE_REPORT_BYTES + 64)
    ascii_path = store.write_stage_report("job-a", "market", ascii_text)
    ascii_report = store.read_stage_report(ascii_path)
    assert ascii_report.truncated is True
    assert ascii_report.full_length == len(ascii_text)
    assert ascii_report.markdown == "x" * MAX_STAGE_REPORT_BYTES

    cjk_text = "中" * (MAX_STAGE_REPORT_BYTES // 3 + 50)
    cjk_path = store.write_stage_report("job-a", "news", cjk_text)
    cjk_report = store.read_stage_report(cjk_path)
    assert cjk_report.truncated is True
    assert cjk_report.full_length == len(cjk_text)
    assert len(cjk_report.markdown.encode("utf-8")) <= MAX_STAGE_REPORT_BYTES
    assert "\ufffd" not in cjk_report.markdown
    assert set(cjk_report.markdown) == {"中"}


def test_stage_report_endpoint_reads_done_stage_and_pending_defaults(env):
    expected = _fake_stage_texts()
    job_id = _create_job(env)
    _run_worker(env)
    pending_job = _create_job(env, "000001")

    before = (
        len(_events(env, job_id)),
        len(_stage_rows(env, job_id)),
        _report_files(env),
    )
    with _client(env) as client:
        response = client.get(f"/api/v1/jobs/{job_id}/stages/market")
        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == job_id
        assert body["stage_id"] == "market"
        assert body["stage_name"] == "技术分析"
        assert body["index"] == 1
        assert body["status"] == "done"
        assert body["markdown"] == expected["market"]
        assert body["truncated"] is False
        assert body["full_length"] == len(expected["market"])
        datetime.fromisoformat(body["updated_at"])

        pending = client.get(f"/api/v1/jobs/{pending_job}/stages/market").json()
        assert pending["status"] == "pending"
        assert pending["markdown"] is None
        assert pending["truncated"] is False
        assert pending["full_length"] == 0
        assert pending["updated_at"] is None

        detail = client.get(f"/api/v1/jobs/{job_id}").json()
        assert [stage["status"] for stage in detail["stages"]] == ["done"] * 12
        assert detail["stats"] == S00_STATS
        assert detail["current_stage"] is None
        assert detail["reconcile_notes"] == []
        assert all(
            stage["duration_ms"] == fake.STAGE_DURATION_MS
            for stage in detail["stages"]
        )
        assert detail["stages"][0]["started_at"] is not None
        assert detail["stages"][0]["finished_at"] is not None

        queued = client.get(f"/api/v1/jobs/{pending_job}").json()
        assert queued["current_stage"] is None
        assert {stage["status"] for stage in queued["stages"]} == {"pending"}
        assert queued["stats"] == {
            "model_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "elapsed_ms": 0,
        }

        unknown_stage = client.get(f"/api/v1/jobs/{job_id}/stages/nope")
        assert unknown_stage.status_code == 404
        assert unknown_stage.json()["error"]["code"] == "stage_not_found"

        missing_job = client.get("/api/v1/jobs/does-not-exist/stages/market")
        assert missing_job.status_code == 404
        assert missing_job.json()["error"]["code"] == "job_not_found"

    assert (
        len(_events(env, job_id)),
        len(_stage_rows(env, job_id)),
        _report_files(env),
    ) == before


def test_stage_report_endpoint_truncates_large_markdown(env):
    job_id = _create_job(env)
    _run_worker(env)

    text = "x" * (MAX_STAGE_REPORT_BYTES + 64)
    path = env.reports.write_stage_report(job_id, "market", text)
    with Session(env.engine) as session:
        row = session.get(JobStage, (job_id, "market"))
        row.report_path = path
        session.commit()

    with _client(env) as client:
        body = client.get(f"/api/v1/jobs/{job_id}/stages/market").json()

    assert body["status"] == "done"
    assert body["truncated"] is True
    assert body["full_length"] == len(text)
    assert body["markdown"] == "x" * MAX_STAGE_REPORT_BYTES


def test_detail_projects_current_stage_and_latest_stats(env):
    job_id = _create_job(env)
    _claim(env)
    env.jobs.start_stage(job_id, "market", index=1, total=12)
    env.jobs.finish_stage(
        job_id,
        "market",
        index=1,
        total=12,
        stats=StatsSnapshot(1, 28000, 4200, 1800000),
        duration_ms=1800000,
    )
    env.jobs.start_stage(job_id, "social", index=2, total=12)

    job = env.jobs.get_job(job_id)
    detail = job_detail(job, **env.jobs.detail_parts(job_id))

    assert detail["current_stage"] == {
        "id": "social",
        "name": "情绪分析",
        "index": 2,
        "total": 12,
        "status": "active",
    }
    assert detail["stats"] == {
        "model_calls": 1,
        "tokens_in": 28000,
        "tokens_out": 4200,
        "elapsed_ms": 1800000,
    }
    assert detail["stages"][0]["status"] == "done"
    assert detail["stages"][0]["duration_ms"] == 1800000
    assert detail["stages"][1]["status"] == "active"
    assert detail["stages"][2]["status"] == "pending"

    with _client(env) as client:
        body = client.get(f"/api/v1/jobs/{job_id}/stages/market").json()
    assert body["status"] == "done"
    assert body["markdown"] is None
    assert body["full_length"] == 0
    assert body["updated_at"] is None


def test_stage_tables_stay_append_only_for_events(env):
    job_id = _create_job(env)
    _run_worker(env)

    before = _events(env, job_id)
    before_sse = sum(1 for event in before if event.seq is not None)
    env.jobs.record_stats(job_id, StatsSnapshot(14, 182430, 41208, 21600000))
    events = _events(env, job_id)

    assert len(events) == len(before) + 1
    assert events[-1].type == "stats"
    assert events[-1].seq == before_sse + 1
    with Session(env.engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq.is_(None))
        ) == 1

"""P1-13 acceptance tests: performance budgets and fault isolation.

P05: server-side event latency (commit -> SSE frame readable) stays under
     500ms, and the inter-stage gap at the executor hook boundary stays within
     5% of the stage's real duration. The fake graph's virtual 30-minute
     durations are never used; the measurement executor sleeps for real.
FT-01: a second ``create_app`` on the same database (new engine, new app)
       resumes from ``Last-Event-ID`` with no holes.
FT-02: two consecutive restarts after a crash still leave ``interrupted``, do
       not re-run the graph, and add no stage artifacts.
FT-03: 20 concurrent creates of the same fingerprint produce one job, and one
       worker execution leaves exactly one attempt per stage.
FT-04: a second SQLite connection holding a write lock makes create/claim wait
       on ``busy_timeout``; after release the job runs once.
FT-05: 1000 broadcast events replay from cursor 0 as ids 1..1000, no holes.
FT-06: two jobs with different config hashes keep their own snapshots, stage
       report directories and detail projections. Runtime config isolation has
       no object in P1 (``AnalysisRequest`` carries no config), so this is the
       data-layer scope from the P1-13 card.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_kernel_perf_faults.py -q
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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
PERF_DIR = Path(__file__).resolve().parent / "perf"
if str(PERF_DIR) not in sys.path:
    sys.path.insert(0, str(PERF_DIR))

import p05_latency  # noqa: E402

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobStage, Report  # noqa: E402
from backend.app.models.stage import STAGE_IDS  # noqa: E402
from backend.app.services.analysis_runner import (  # noqa: E402
    FakeAnalysisExecutor,
    StageProgress,
)
from backend.app.services.event_log import append_event  # noqa: E402
from backend.app.services.event_stream import EventStream  # noqa: E402
from backend.app.services.job_service import (  # noqa: E402
    CST,
    JobService,
    StatsSnapshot,
)
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
MEDIA = {"Accept": "text/event-stream"}
TOTAL_EVENTS = 40
BUSY_HOLD_SECONDS = 0.25


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
    stream = EventStream(jobs, poll_interval=0.005, heartbeat_interval=60.0)
    app = create_app(
        service=jobs,
        server_config=SERVER_CONFIG,
        report_store=reports,
        event_stream=stream,
    )
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            db_path=path,
            engine=engine,
            jobs=jobs,
            reports=reports,
            clock=clock,
            stream=stream,
            app=app,
            client=client,
            lease=lambda **kwargs: LeaseService(engine, clock=clock, **kwargs),
        )
    finally:
        client.close()
        engine.dispose()


def _create(env, ticker: str = "000629", config: dict | None = None) -> str:
    outcome = env.jobs.create_job(
        {
            "ticker": ticker,
            "analysis_date": TODAY,
            "config": dict(config or CONFIG),
        },
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def _run(env, executor=None, *, owner: str = "worker-test"):
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner=owner,
        executor=executor,
        reconcile_on_start=False,
    )
    assert worker.acquire() is True
    try:
        outcome = worker.run_once()
        assert outcome is not None
        return outcome
    finally:
        worker.shutdown()


def _reconcile(env, *, owner: str):
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner=owner,
        reconcile_on_start=True,
    )
    assert worker.acquire() is True
    return worker


def _claim(env, job_id: str, owner: str = "worker-crashed") -> None:
    lease = env.lease()
    assert lease.acquire(owner) is True
    claimed = lease.claim_next_job(owner)
    assert claimed is not None and claimed.id == job_id
    assert lease.release(owner) is True


def _status(env, job_id: str) -> str:
    job = env.jobs.get_job(job_id)
    assert job is not None
    return job.status


def _detail(env, job_id: str, client=None) -> dict:
    response = (client or env.client).get(f"/api/v1/jobs/{job_id}")
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


def _broadcast(env, job_id: str) -> list[JobEvent]:
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


def _frames(text: str) -> list[dict]:
    parsed = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        frame = {
            "retry": None,
            "comment": None,
            "id": None,
            "event": None,
            "data": None,
        }
        data_lines = []
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            elif line.startswith("retry: "):
                frame["retry"] = int(line[7:])
            elif line.startswith("id: "):
                frame["id"] = int(line[4:])
            elif line.startswith("event: "):
                frame["event"] = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        if data_lines:
            frame["data"] = json.loads("\n".join(data_lines))
        parsed.append(frame)
    return parsed


def _data_frames(text: str) -> list[dict]:
    return [frame for frame in _frames(text) if frame["data"] is not None]


def _new_app(env) -> tuple:
    """A second process-equivalent: new engine, service, stream and app."""
    engine = build_engine(env.db_path)
    reports = ReportStore(env.reports.root)
    jobs = JobService(engine, SERVER_CONFIG, clock=env.clock, reports=reports)
    stream = EventStream(jobs, poll_interval=0.005, heartbeat_interval=60.0)
    app = create_app(
        service=jobs,
        server_config=SERVER_CONFIG,
        report_store=reports,
        event_stream=stream,
    )
    return engine, TestClient(app)


def _artifact_snapshot(env) -> dict[str, int]:
    root = env.reports.root
    return {
        path.relative_to(root).as_posix(): path.stat().st_size
        for path in root.rglob("*")
        if path.is_file()
    }


def _complete_stage(env, job_id: str, index: int) -> None:
    stage_id = STAGE_IDS[index - 1]
    env.jobs.start_stage(job_id, stage_id, index=index, total=len(STAGE_IDS))
    path = env.reports.write_stage_report(
        job_id, stage_id, f"{stage_id} 报告：attempt for {job_id}"
    )
    env.jobs.finish_stage(
        job_id,
        stage_id,
        index=index,
        total=len(STAGE_IDS),
        stats=StatsSnapshot(model_calls=1, tokens_in=1, tokens_out=1, elapsed_ms=1),
        report_path=path,
        duration_ms=1,
    )


def _start_thread(fn):
    box: dict[str, object] = {}

    def _target() -> None:
        began = time.monotonic()
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - surfaced by _join
            box["error"] = exc
        box["elapsed"] = time.monotonic() - began

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread, box


def _join(thread, box, *, timeout: float = 20.0):
    thread.join(timeout)
    assert not thread.is_alive(), "background thread did not finish"
    if "error" in box:
        raise box["error"]
    return box["value"]


class _GatedExecutor:
    """Blocks after the first stage so another thread can inspect the run."""

    name = "gated"

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()
        self._inner = FakeAnalysisExecutor()

    def run(self, request, *, on_stage=None, on_chunk=None):
        def hook(progress: StageProgress) -> None:
            if on_stage is not None:
                on_stage(progress)
            if progress.phase == "done" and progress.index == 1:
                self.reached.set()
                assert self.release.wait(20.0)

        return self._inner.run(request, on_stage=hook, on_chunk=on_chunk)


# -- P05 ------------------------------------------------------------------


def test_p05_server_latency_and_stage_gap_stay_within_budget():
    saved = os.environ.get(JOBS_DB_ENV)
    try:
        measurement = p05_latency.measure()
    finally:
        if saved is None:
            os.environ.pop(JOBS_DB_ENV, None)
        else:
            os.environ[JOBS_DB_ENV] = saved

    latency = measurement["latency"]["latency_samples_ms"]
    deviations = measurement["gaps"]["deviation_samples_percent"]

    assert len(latency) == 5
    assert len(deviations) == len(STAGE_IDS) - 1
    assert statistics.median(latency) <= p05_latency.LATENCY_BUDGET_MS
    assert (
        statistics.median(deviations)
        <= p05_latency.STAGE_GAP_BUDGET_PERCENT
    )
    assert all(value >= 0 for value in latency)
    assert all(value >= 0 for value in deviations)


# -- FT-01 ----------------------------------------------------------------


def test_ft01_restarted_app_replays_from_last_event_id(env):
    job_id = _create(env)
    _run(env)
    assert len(_broadcast(env, job_id)) == TOTAL_EVENTS

    url = f"/api/v1/jobs/{job_id}/events"
    consumed: list[tuple[str, int]] = []
    first_headers = {**MEDIA, "Last-Event-ID": "0"}
    with env.client.stream("GET", url, headers=first_headers) as response:
        assert response.status_code == 200
        pending_id = None
        for line in response.iter_lines():
            if line.startswith("id: "):
                pending_id = int(line[4:])
            elif line.startswith("event: ") and pending_id is not None:
                consumed.append((line[7:], pending_id))
                pending_id = None
                if len(consumed) == 4:
                    break
    assert consumed[0][0] == "snapshot"
    assert [frame_id for _name, frame_id in consumed[1:]] == [1, 2, 3]
    assert all(name != "snapshot" for name, _id in consumed[1:])
    cursor = consumed[-1][1]

    engine, client = _new_app(env)
    try:
        response = client.get(
            url, headers={**MEDIA, "Last-Event-ID": str(cursor)}
        )
        assert response.status_code == 200
        detail = _detail(env, job_id, client=client)
    finally:
        client.close()
        engine.dispose()

    frames = _data_frames(response.text)
    assert frames[0]["event"] == "snapshot"
    assert frames[0]["id"] == TOTAL_EVENTS
    assert frames[0]["data"]["payload"]["job"] == detail
    replayed = frames[1:]
    assert [frame["id"] for frame in replayed] == list(
        range(cursor + 1, TOTAL_EVENTS + 1)
    )
    assert [frame["event"] for frame in replayed] == [
        event.type for event in _broadcast(env, job_id)[cursor:]
    ]


# -- FT-02 ----------------------------------------------------------------


def test_ft02_second_restart_keeps_interrupted_and_adds_nothing(env):
    job_id = _create(env)
    _claim(env, job_id)
    _complete_stage(env, job_id, 1)
    _complete_stage(env, job_id, 2)
    artifacts = _artifact_snapshot(env)

    first = _reconcile(env, owner="restart-1")
    first.shutdown()
    assert _status(env, job_id) == "interrupted"
    resume_point = env.jobs.get_job(job_id).resume_from_stage
    assert resume_point == "news"
    first_events = [
        (event.seq, event.type, dict(event.payload))
        for event in _events(env, job_id)
    ]
    first_stages = {
        stage_id: (row.status, row.report_path)
        for stage_id, row in _stage_rows(env, job_id).items()
    }

    second = _reconcile(env, owner="restart-2")
    try:
        assert second.claim() is None
    finally:
        second.shutdown()

    assert _status(env, job_id) == "interrupted"
    assert env.jobs.get_job(job_id).resume_from_stage == resume_point
    assert _artifact_snapshot(env) == artifacts
    assert [
        (event.seq, event.type, dict(event.payload))
        for event in _events(env, job_id)
    ] == first_events
    assert {
        stage_id: (row.status, row.report_path)
        for stage_id, row in _stage_rows(env, job_id).items()
    } == first_stages
    assert _report_row(env, job_id) is None
    assert env.reports.read_final_report(job_id) is None


# -- FT-03 ----------------------------------------------------------------


def test_ft03_twenty_concurrent_creates_run_once(env):
    ticker = "000001"
    body = {
        "ticker": ticker,
        "analysis_date": TODAY,
        "config": dict(CONFIG),
    }
    keys = [str(uuid.uuid4()) for _ in range(20)]
    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(
            pool.map(
                lambda key: env.jobs.create_job(body, idempotency_key=key),
                keys,
            )
        )
    job_ids = {outcome.job.id for outcome in outcomes}
    assert len(job_ids) == 1
    assert sum(outcome.status_code == 201 for outcome in outcomes) == 1
    job_id = job_ids.pop()

    outcome = _run(env)
    assert outcome.result is not None
    assert _status(env, job_id) == "succeeded"
    assert _job_count(env) == 1

    job_dir = env.reports.root / job_id
    assert sorted(path.name for path in job_dir.iterdir() if path.is_dir()) == sorted(
        STAGE_IDS
    )
    for stage_id in STAGE_IDS:
        attempts = sorted(
            path.name for path in (job_dir / stage_id).glob("attempt-*.md")
        )
        assert attempts == ["attempt-1.md"]

    assert len(_broadcast(env, job_id)) == TOTAL_EVENTS
    assert len(_stage_rows(env, job_id)) == len(STAGE_IDS)


# -- FT-04 ----------------------------------------------------------------


def test_ft04_write_lock_makes_create_and_claim_wait(env):
    env.jobs.get_job("warmup")  # open the pooled connection before locking
    lock = sqlite3.connect(str(env.db_path), timeout=5.0, isolation_level=None)
    try:
        lock.execute("BEGIN IMMEDIATE")
        thread, box = _start_thread(
            lambda: env.jobs.create_job(
                {
                    "ticker": "600519",
                    "analysis_date": TODAY,
                    "config": dict(CONFIG),
                },
                idempotency_key=str(uuid.uuid4()),
            )
        )
        time.sleep(BUSY_HOLD_SECONDS)
        assert thread.is_alive(), "create should wait on the write lock"
        lock.execute("ROLLBACK")
        created = _join(thread, box)
    finally:
        lock.close()

    assert created.status_code == 201
    assert box["elapsed"] >= BUSY_HOLD_SECONDS - 0.05
    job_id = created.job.id

    env.clock.advance(seconds=1)
    other_id = _create(env, ticker="000629")
    assert other_id != job_id
    lock = sqlite3.connect(str(env.db_path), timeout=5.0, isolation_level=None)
    try:
        lock.execute("BEGIN IMMEDIATE")

        def _run_worker():
            worker = Worker(
                env.lease(),
                jobs=env.jobs,
                reports=env.reports,
                owner="worker-busy",
                reconcile_on_start=False,
            )
            assert worker.acquire() is True
            try:
                return worker.run_once()
            finally:
                worker.shutdown()

        thread, box = _start_thread(_run_worker)
        time.sleep(BUSY_HOLD_SECONDS)
        assert thread.is_alive(), "claim should wait on the write lock"
        lock.execute("ROLLBACK")
        outcome = _join(thread, box)
    finally:
        lock.close()

    assert outcome is not None and outcome.result is not None
    assert box["elapsed"] >= BUSY_HOLD_SECONDS - 0.05
    assert _status(env, job_id) == "succeeded"
    assert _status(env, other_id) == "queued"
    assert _job_count(env) == 2

    rows = _stage_rows(env, job_id)
    assert len(rows) == len(STAGE_IDS)
    assert {row.status for row in rows.values()} == {"done"}
    for stage_id in STAGE_IDS:
        attempts = sorted(
            path.name
            for path in (env.reports.root / job_id / stage_id).glob(
                "attempt-*.md"
            )
        )
        assert attempts == ["attempt-1.md"]
    assert len(_broadcast(env, job_id)) == TOTAL_EVENTS


# -- FT-05 ----------------------------------------------------------------


def test_ft05_thousand_events_replay_without_holes(env):
    # A terminal job ends the HTTP stream after replay; a queued job would
    # switch to live follow and never finish the response.
    job_id = _create(env)
    _run(env)
    assert _status(env, job_id) == "succeeded"
    baseline = len(_broadcast(env, job_id))
    assert baseline == TOTAL_EVENTS

    created_at = env.jobs.now().isoformat(timespec="seconds")
    with Session(env.engine) as session:
        for probe in range(1000):
            append_event(
                session,
                job_id=job_id,
                event_type="stage_changed",
                payload={"probe": probe},
                created_at=created_at,
            )
        session.commit()
    max_seq = baseline + 1000

    response = env.client.get(
        f"/api/v1/jobs/{job_id}/events",
        headers={**MEDIA, "Last-Event-ID": "0"},
    )
    assert response.status_code == 200
    frames = _data_frames(response.text)
    assert frames[0]["event"] == "snapshot"
    assert frames[0]["id"] == max_seq
    assert frames[0]["data"]["payload"]["last_seq"] == max_seq

    replayed = frames[1:]
    assert [frame["id"] for frame in replayed] == list(range(1, max_seq + 1))
    probes = [frame for frame in replayed if frame["id"] > baseline]
    assert len(probes) == 1000
    assert all(frame["event"] == "stage_changed" for frame in probes)
    assert [frame["data"]["payload"]["probe"] for frame in probes] == list(
        range(1000)
    )


# -- FT-06 ----------------------------------------------------------------


def test_ft06_config_and_report_dirs_stay_isolated(env):
    config_a = dict(CONFIG)
    config_b = {**CONFIG, "parallel_analysts": False}
    job_a = _create(env, ticker="000629", config=config_a)
    env.clock.advance(seconds=1)
    job_b = _create(env, ticker="600519", config=config_b)

    before = {
        job_a: dict(env.jobs.get_job(job_a).config_snapshot),
        job_b: dict(env.jobs.get_job(job_b).config_snapshot),
    }
    hash_a = env.jobs.get_job(job_a).config_hash
    hash_b = env.jobs.get_job(job_b).config_hash
    assert hash_a != hash_b

    gated = _GatedExecutor()
    thread, box = _start_thread(lambda: _run(env, gated, owner="worker-a"))
    try:
        assert gated.reached.wait(20.0)
        assert _status(env, job_a) == "running"
        assert _status(env, job_b) == "queued"
        assert env.jobs.get_job(job_a).config_snapshot == before[job_a]
        assert env.jobs.get_job(job_b).config_snapshot == before[job_b]
        assert env.lease().acquire("worker-b") is False

        detail_b = _detail(env, job_b)
        assert detail_b["job_id"] == job_b
        assert detail_b["config_digest"] == hash_b
        assert detail_b["status"] == "queued"
        assert all(stage["status"] == "pending" for stage in detail_b["stages"])
    finally:
        gated.release.set()
    outcome_a = _join(thread, box)

    assert outcome_a.result is not None
    assert _status(env, job_a) == "succeeded"
    assert _status(env, job_b) == "queued"

    outcome_b = _run(env)
    assert outcome_b.result is not None
    assert _status(env, job_b) == "succeeded"

    for job_id, expected_hash, expected_snapshot in (
        (job_a, hash_a, before[job_a]),
        (job_b, hash_b, before[job_b]),
    ):
        job = env.jobs.get_job(job_id)
        assert job.config_snapshot == expected_snapshot
        assert job.config_hash == expected_hash
        detail = _detail(env, job_id)
        assert detail["job_id"] == job_id
        assert detail["config_digest"] == expected_hash
        assert all(stage["status"] == "done" for stage in detail["stages"])

        job_dir = env.reports.root / job_id
        assert sorted(
            path.name for path in job_dir.iterdir() if path.is_dir()
        ) == sorted(STAGE_IDS)
        for stage_id in STAGE_IDS:
            assert [
                path.name for path in (job_dir / stage_id).glob("attempt-*.md")
            ] == ["attempt-1.md"]

        rows = _stage_rows(env, job_id)
        assert len(rows) == len(STAGE_IDS)
        assert all(
            row.report_path.startswith(f"{job_id}/")
            for row in rows.values()
        )

    assert {path.name for path in env.reports.root.iterdir()} == {
        job_a,
        job_b,
    }

"""P1-06 acceptance tests: fake executor adapter.

GF-05: the default path opens no socket, imports no model SDK and writes
       nothing under the real user report directory.
GF-06: the fake chunk stream drives the real ProgressTracker stage detection.
S00: 14 model calls, 182430 input tokens, 41208 output tokens and 40 events,
     matching the fake-graph documents.
AD-01: the real runner stays off by default; it needs both the environment
       variable and the server config flag before the factory refuses to fake.
"""

from __future__ import annotations

import ast
import socket
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.fake_analysis_graph as fake  # noqa: E402
from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.models import Job  # noqa: E402
from backend.app.services.analysis_runner import (  # noqa: E402
    REAL_RUNNER_ENV,
    AnalysisRequest,
    AnalysisRunError,
    FakeAnalysisExecutor,
    RunResult,
    RunStats,
    create_analysis_executor,
    real_runner_enabled,
)
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402
from web.progress import STAGE_IDS as REAL_STAGE_IDS  # noqa: E402
from web.progress import ProgressTracker  # noqa: E402
from web.runner import _detect_completed_stages, _infer_active_stage  # noqa: E402

REQUEST = AnalysisRequest(ticker_code="000629", analysis_date="2026-10-24")
BACKEND = ROOT / "backend"
CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}
S00_STATS = RunStats(
    model_calls=14,
    tokens_in=182430,
    tokens_out=41208,
    elapsed_ms=21600000,
)
BANNED_IMPORT_ROOTS = {
    "tradingagents",
    "web",
    "requests",
    "urllib",
    "http",
    "socket",
    "openai",
    "anthropic",
    "dashscope",
    "google",
}


def _imported_roots(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_gf05_default_path_has_no_network_model_or_real_report_writes(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in the fake executor")

    legacy_dir = Path.home() / ".tradingagents"
    before = _tree_snapshot(legacy_dir)

    monkeypatch.setattr(socket, "socket", _blocked)
    executor = create_analysis_executor(ServerConfig(), environ={})
    result = executor.run(REQUEST)

    assert result.stages_completed == fake.STAGE_IDS
    assert _tree_snapshot(legacy_dir) == before

    runner_path = (
        ROOT / "backend" / "app" / "services" / "analysis_runner.py"
    )
    assert not _imported_roots(runner_path) & BANNED_IMPORT_ROOTS
    assert _imported_roots(Path(fake.__file__)) & BANNED_IMPORT_ROOTS == set()

    source = runner_path.read_text(encoding="utf-8")
    for needle in ("write_text(", "write_bytes(", "Path.home(", "time.sleep"):
        assert needle not in source, needle


def test_gf06_fake_stream_drives_real_progress_tracker():
    tracker = ProgressTracker(ticker="000629", trade_date="2026-10-24")
    tracker.is_running = True

    executor = FakeAnalysisExecutor()
    result = executor.run(
        REQUEST,
        on_chunk=lambda chunk: (
            _detect_completed_stages(chunk, tracker),
            _infer_active_stage(tracker),
        ),
    )

    assert tracker.completed_stages == list(REAL_STAGE_IDS)
    assert set(tracker.stage_reports) == set(REAL_STAGE_IDS)
    assert tracker.stage_status("market") == "done"
    assert tracker.stage_status("pm") == "done"
    assert result.stages_completed == tuple(REAL_STAGE_IDS)
    assert tracker.snapshot()["stage_reports"] == tracker.stage_reports


def test_s00_executor_stats_match_the_fake_graph_documents():
    outcome = fake.run_scenario("S00")
    executor = create_analysis_executor(ServerConfig(), environ={})
    result = executor.run(REQUEST)

    assert result.stats == S00_STATS
    assert result.stats.model_calls == outcome.job["stats"]["model_calls"]
    assert result.stats.tokens_in == outcome.job["stats"]["tokens_in"]
    assert result.stats.tokens_out == outcome.job["stats"]["tokens_out"]
    assert result.stats.elapsed_ms == outcome.job["stats"]["elapsed_ms"]

    assert len(outcome.events) == 40
    assert sum(event["type"] == "stage_changed" for event in outcome.events) == 24
    assert sum(event["type"] == "stats" for event in outcome.events) == 13
    assert [event["seq"] for event in outcome.events] == list(range(1, 41))

    assert result.signal == outcome.report["meta"]["signal"]
    assert result.stages_completed == fake.STAGE_IDS
    assert result.last_chunk["final_trade_decision"]


def test_executor_reports_each_stage_started_then_done_with_usage():
    updates: list = []
    result = FakeAnalysisExecutor().run(REQUEST, on_stage=updates.append)

    assert len(updates) == 24
    assert [u.stage_id for u in updates[::2]] == list(fake.STAGE_IDS)
    assert [u.stage_id for u in updates[1::2]] == list(fake.STAGE_IDS)
    assert [u.phase for u in updates[::2]] == ["started"] * 12
    assert [u.phase for u in updates[1::2]] == ["done"] * 12
    assert [u.index for u in updates[::2]] == list(range(1, 13))
    assert {u.total for u in updates} == {12}
    assert all(u.report_text is None for u in updates[::2])
    assert all(u.report_text for u in updates[1::2])

    done = updates[1::2]
    assert sum(u.model_calls for u in done) == 14
    assert sum(u.tokens_in for u in done) == result.stats.tokens_in
    assert sum(u.tokens_out for u in done) == result.stats.tokens_out
    for update, spec in zip(done, fake.STAGES, strict=True):
        assert (update.model_calls, update.tokens_in, update.tokens_out) == (
            spec.model_calls,
            spec.tokens_in,
            spec.tokens_out,
        )
        assert update.stage_name == spec.name


def test_ad01_real_runner_needs_environment_and_config(monkeypatch):
    default = create_analysis_executor(ServerConfig(), environ={})
    assert isinstance(default, FakeAnalysisExecutor)
    assert default.name == "fake"

    env_only = create_analysis_executor(
        ServerConfig(), environ={REAL_RUNNER_ENV: "1"}
    )
    assert isinstance(env_only, FakeAnalysisExecutor)

    config_only = create_analysis_executor(
        ServerConfig(real_runner_enabled=True), environ={}
    )
    assert isinstance(config_only, FakeAnalysisExecutor)

    assert real_runner_enabled(ServerConfig(), environ={}) is False
    assert real_runner_enabled(
        ServerConfig(), environ={REAL_RUNNER_ENV: "1"}
    ) is False
    assert real_runner_enabled(ServerConfig(real_runner_enabled=True), environ={}) is False
    assert real_runner_enabled(
        ServerConfig(real_runner_enabled=True), environ={REAL_RUNNER_ENV: "1"}
    ) is True
    assert real_runner_enabled(
        ServerConfig(real_runner_enabled=True), environ={REAL_RUNNER_ENV: "true"}
    ) is False

    with pytest.raises(AnalysisRunError) as excinfo:
        create_analysis_executor(
            ServerConfig(real_runner_enabled=True), environ={REAL_RUNNER_ENV: "1"}
        )
    assert excinfo.value.code == "real_runner_unavailable"

    monkeypatch.delenv(REAL_RUNNER_ENV, raising=False)
    assert isinstance(create_analysis_executor(ServerConfig()), FakeAnalysisExecutor)


def test_executor_uses_the_requested_ticker_and_date():
    class _RecordingGraph(fake.FakeAnalysisGraph):
        def __init__(self, ticker, analysis_date):
            super().__init__(ticker, analysis_date)
            self.prepared: tuple[str, str] | None = None

        def prepare_graph_run(self, ticker, trade_date, callbacks=None):
            self.prepared = (ticker, trade_date)
            return super().prepare_graph_run(ticker, trade_date, callbacks=callbacks)

    class _Module:
        STAGES = fake.STAGES
        extract_stage_text = staticmethod(fake.extract_stage_text)
        graph = None

        def FakeAnalysisGraph(self, ticker, analysis_date):
            self.graph = _RecordingGraph(ticker, analysis_date)
            return self.graph

    module = _Module()
    result = FakeAnalysisExecutor(fake_module=module).run(
        AnalysisRequest(ticker_code="600519", analysis_date="2026-10-23")
    )

    assert module.graph.prepared == ("600519", "2026-10-23")
    assert result.stages_completed == tuple(spec.id for spec in fake.STAGES)


def test_stage_catalog_mismatch_fails_loudly():
    class _Module:
        STAGES = (fake.StageSpec("market", "技术分析", "market_report", 1, 1, 1),)

    with pytest.raises(AnalysisRunError) as excinfo:
        FakeAnalysisExecutor(fake_module=_Module()).run(REQUEST)
    assert excinfo.value.code == "stage_catalog_mismatch"


class _FixedClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def worker_env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    command.upgrade(_alembic_config(), "head")

    clock = _FixedClock(datetime(2026, 10, 30, 9, 0, tzinfo=CST))
    engine = build_engine()
    jobs = JobService(engine, ServerConfig(), clock=clock)
    try:
        yield SimpleNamespace(
            engine=engine,
            jobs=jobs,
            lease=LeaseService(engine, clock=clock),
        )
    finally:
        engine.dispose()


def _create_job(env) -> str:
    outcome = env.jobs.create_job(
        {
            "ticker": "000629",
            "analysis_date": "2026-10-30",
            "config": dict(CONFIG),
        },
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def test_worker_run_once_claims_then_runs_the_fake_graph(worker_env, monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in the fake executor")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.delenv(REAL_RUNNER_ENV, raising=False)
    job_id = _create_job(worker_env)

    worker = Worker(worker_env.lease, owner="worker-1")
    try:
        assert worker.acquire() is True
        outcome = worker.run_once()

        assert outcome is not None
        job, result = outcome
        assert job.id == job_id
        assert result.stats == S00_STATS
        assert result.stages_completed == fake.STAGE_IDS

        with Session(worker_env.engine) as session:
            row = session.get(Job, job_id)
            assert row.status == "running"
            assert row.lease_owner == "worker-1"
        assert worker.run_once() is None
    finally:
        worker.shutdown()


def test_worker_executor_is_injectable(worker_env):
    class _StubExecutor:
        name = "stub"

        def __init__(self) -> None:
            self.requests: list[AnalysisRequest] = []

        def run(self, request, *, on_stage=None, on_chunk=None):
            self.requests.append(request)
            return RunResult(
                signal="Hold",
                stats=RunStats(),
                stages_completed=(),
                last_chunk={},
            )

    job_id = _create_job(worker_env)
    stub = _StubExecutor()
    worker = Worker(worker_env.lease, owner="worker-1", executor=stub)
    try:
        assert worker.acquire() is True
        outcome = worker.run_once()

        assert outcome is not None
        assert outcome[0].id == job_id
        assert stub.requests == [
            AnalysisRequest(ticker_code="000629", analysis_date="2026-10-30")
        ]
    finally:
        worker.shutdown()

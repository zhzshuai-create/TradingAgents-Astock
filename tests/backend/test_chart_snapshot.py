"""RPT-01 acceptance tests: chart snapshot evidence and the frozen rule.

RPT-T1  usable quote + daily K, real worker run: ``frozen`` and the sidecar's
        ``report_content_hash`` equals the report row's ``content_hash``.
RPT-T2  K line error: ``none`` / ``kline_error``, file still written, run ok.
RPT-T3  snapshotter raises: ``none``, run ok, no file, exception logged.
RPT-T4  disk write raises OSError: ``none``, run ok, row never frozen.
RPT-T5  default (no snapshotter): ``none``, no file.
RPT-T6  stale blocks with data still freeze and keep their ``as_of``.
RPT-T7  empty quote: ``none`` / ``quote_empty``.
RPT-T8  pause_noop and cancel_noop take the same path as T03.
RPT-T9  a lost heartbeat never captures.
RPT-T10 the run_backend wiring function honours ``TA_CHART_SNAPSHOT=0``.
RPT-T11 the reader rejects corrupt JSON and a wrong schema version.

Every test is offline: providers are :class:`FakeMarketProviders`, the graph is
the deterministic fake, and no test writes outside ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tests.fake_analysis_graph as fake  # noqa: E402
from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Report  # noqa: E402
from backend.app.services.analysis_runner import FakeAnalysisExecutor  # noqa: E402
from backend.app.services.chart_snapshot import (  # noqa: E402
    CHART_SNAPSHOT_VERSION,
    MarketChartSnapshotter,
)
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.market_cache import MarketCache  # noqa: E402
from backend.app.services.market_providers import (  # noqa: E402
    FakeMarketProviders,
    Fetched,
)
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.services.stock_service import StockService  # noqa: E402
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

QUOTE = {"name": "攀钢钒钛", "price": 3.21, "change_pct": 0.94}
KLINE = {
    "adjust": "none",
    "bars": [
        {"date": "2026-10-29", "open": 3.1, "high": 3.3, "low": 3.0, "close": 3.2}
    ],
    "units": {"price": "元", "volume": "手", "amount": "元"},
}


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


def _providers(*, quote=None, kline=None, kline_error=None) -> FakeMarketProviders:
    providers = FakeMarketProviders()
    providers.set("quote", quote)
    providers.set("kline", kline, error=kline_error)
    return providers


def _snapshotter(providers: FakeMarketProviders) -> MarketChartSnapshotter:
    stock = StockService(
        providers, MarketCache(clock=lambda: CLOCK), clock=lambda: CLOCK
    )
    return MarketChartSnapshotter(stock, clock=lambda: CLOCK)


def _run(env, snapshotter=None, *, executor=None, trigger=None, after_stage=None):
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner="worker-test",
        executor=executor,
        chart_snapshotter=snapshotter,
    )
    assert worker.acquire() is True
    try:
        if trigger is None:
            return worker.run_once()
        return _run_with_trigger(env, worker, trigger, after_stage)
    finally:
        worker.shutdown()


class _Injector:
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


def _run_with_trigger(env, worker, trigger, after_stage):
    worker._executor = _Injector(after_stage, trigger)
    return worker.run_once()


def _report_row(env, job_id: str) -> Report:
    job = env.jobs.get_job(job_id)
    assert job is not None and job.report_id is not None
    with Session(env.engine) as session:
        row = session.get(Report, job.report_id)
        assert row is not None
        return row


def _snapshot_path(env, job_id: str) -> Path:
    return env.reports.root / job_id / "chart_snapshot.json"


def _snapshot(env, job_id: str) -> dict:
    path = _snapshot_path(env, job_id)
    assert path.is_file()
    return json.loads(path.read_text(encoding="utf-8"))


def test_rpt_t1_frozen_row_matches_the_written_evidence(env):
    job_id = _create_job(env)
    providers = _providers(
        quote=Fetched(data=QUOTE, as_of=CLOCK.isoformat(), source="tencent"),
        kline=Fetched(data=KLINE, as_of=CLOCK.isoformat(), source="mootdx"),
    )
    outcome = _run(env, _snapshotter(providers))
    assert outcome is not None and outcome.result is not None
    assert env.jobs.get_job(job_id).status == "succeeded"

    row = _report_row(env, job_id)
    snapshot = _snapshot(env, job_id)
    assert row.chart_snapshot_status == "frozen"
    assert row.payload["meta"]["chart_snapshot_status"] == "frozen"
    assert snapshot["schema_version"] == CHART_SNAPSHOT_VERSION
    assert snapshot["ticker"] == "000629"
    assert snapshot["status"] == "frozen"
    assert snapshot["reason"] is None
    assert snapshot["report_content_hash"] == row.content_hash
    assert snapshot["blocks"]["quote"]["source"] == "tencent"
    assert snapshot["blocks"]["kline"]["data"]["bars"] == KLINE["bars"]


def test_rpt_t2_kline_error_keeps_the_run_green(env):
    job_id = _create_job(env)
    providers = _providers(
        quote=Fetched(data=QUOTE, as_of=CLOCK.isoformat(), source="tencent"),
        kline_error=RuntimeError("mootdx down"),
    )
    _run(env, _snapshotter(providers))

    row = _report_row(env, job_id)
    snapshot = _snapshot(env, job_id)
    assert row.chart_snapshot_status == "none"
    assert snapshot["status"] == "none"
    assert snapshot["reason"] == "kline_error"
    assert snapshot["report_content_hash"] == row.content_hash
    assert env.reports.read_final_report(job_id) is not None
    assert env.jobs.get_job(job_id).status == "succeeded"


def test_rpt_t3_snapshotter_crash_is_downgraded(env, caplog):
    job_id = _create_job(env)

    class Bomb:
        def capture(self, ticker, *, content_hash):
            raise RuntimeError("capture exploded")

    with caplog.at_level("ERROR", logger="backend.app.worker.main"):
        _run(env, Bomb())

    assert _report_row(env, job_id).chart_snapshot_status == "none"
    assert not _snapshot_path(env, job_id).exists()
    assert env.jobs.get_job(job_id).status == "succeeded"
    assert "chart snapshot capture failed" in caplog.text
    assert "capture exploded" in caplog.text


def test_rpt_t4_disk_error_is_downgraded(env, monkeypatch):
    job_id = _create_job(env)
    providers = _providers(
        quote=Fetched(data=QUOTE, as_of=CLOCK.isoformat(), source="tencent"),
        kline=Fetched(data=KLINE, as_of=CLOCK.isoformat(), source="mootdx"),
    )

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(env.reports, "write_chart_snapshot", fail)
    _run(env, _snapshotter(providers))

    assert _report_row(env, job_id).chart_snapshot_status == "none"
    assert env.jobs.get_job(job_id).status == "succeeded"
    assert not _snapshot_path(env, job_id).exists()


def test_rpt_t5_default_worker_writes_nothing(env):
    job_id = _create_job(env)
    _run(env)

    assert _report_row(env, job_id).chart_snapshot_status == "none"
    assert not _snapshot_path(env, job_id).exists()


def test_rpt_t6_stale_blocks_still_freeze_and_keep_as_of(env):
    job_id = _create_job(env)
    stale_as_of = "2026-10-29"
    providers = _providers(
        quote=Fetched(
            data=QUOTE,
            as_of=stale_as_of,
            source="tencent",
            status="stale",
            stale_reason="ttl_exceeded",
        ),
        kline=Fetched(
            data=KLINE,
            as_of="2026-10-28",
            source="mootdx",
            status="stale",
            stale_reason="trading_day_mismatch",
        ),
    )
    _run(env, _snapshotter(providers))

    snapshot = _snapshot(env, job_id)
    assert _report_row(env, job_id).chart_snapshot_status == "frozen"
    assert snapshot["status"] == "frozen"
    assert snapshot["blocks"]["quote"]["status"] == "stale"
    assert snapshot["blocks"]["quote"]["as_of"] == stale_as_of
    assert snapshot["blocks"]["kline"]["as_of"] == "2026-10-28"


def test_rpt_t7_empty_quote_is_none(env):
    job_id = _create_job(env)
    providers = _providers(
        quote=Fetched(status="empty", data=None, as_of=None, source="tencent"),
        kline=Fetched(data=KLINE, as_of=CLOCK.isoformat(), source="mootdx"),
    )
    _run(env, _snapshotter(providers))

    snapshot = _snapshot(env, job_id)
    assert _report_row(env, job_id).chart_snapshot_status == "none"
    assert snapshot["status"] == "none"
    assert snapshot["reason"] == "quote_empty"


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_rpt_t8_control_noop_paths_freeze_identically(env, action):
    job_id = _create_job(env)
    providers = _providers(
        quote=Fetched(data=QUOTE, as_of=CLOCK.isoformat(), source="tencent"),
        kline=Fetched(data=KLINE, as_of=CLOCK.isoformat(), source="mootdx"),
    )

    def trigger():
        response = env.client.post(
            f"/api/v1/jobs/{job_id}/actions", json={"action": action}
        )
        assert response.status_code == 202
        assert response.json()["status"] == f"{action}_requested"

    outcome = _run(
        env,
        _snapshotter(providers),
        trigger=trigger,
        after_stage=fake.STAGE_IDS[-1],
    )
    assert outcome is not None
    assert outcome.stopped == f"{action}_requested"

    snapshot = _snapshot(env, job_id)
    assert _report_row(env, job_id).chart_snapshot_status == "frozen"
    assert snapshot["status"] == "frozen"
    wrote = list((env.reports.root / job_id).glob("chart_snapshot.json*"))
    assert len(wrote) == 1 and wrote[0].name == "chart_snapshot.json"


def test_rpt_t9_lost_heartbeat_never_captures(env):
    job_id = _create_job(env)
    providers = _providers(
        quote=Fetched(data=QUOTE, as_of=CLOCK.isoformat(), source="tencent"),
        kline=Fetched(data=KLINE, as_of=CLOCK.isoformat(), source="mootdx"),
    )
    holder: dict[str, Worker] = {}

    def trigger():
        holder["worker"]._heartbeat._lost.set()

    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner="worker-test",
        executor=_Injector(fake.STAGE_IDS[-1], trigger),
        chart_snapshotter=_snapshotter(providers),
    )
    holder["worker"] = worker
    assert worker.acquire() is True
    try:
        outcome = worker.run_once()
    finally:
        worker.shutdown()

    assert outcome is not None and outcome.stopped == "lost"
    assert not _snapshot_path(env, job_id).exists()
    assert env.jobs.get_job(job_id).status == "running"


def test_rpt_t10_run_backend_switch():
    spec = importlib.util.spec_from_file_location(
        "run_backend_rpt01", ROOT / "scripts" / "run_backend.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    providers = FakeMarketProviders()
    cache = MarketCache()
    assert isinstance(
        module.build_chart_snapshotter(providers, cache, {}),
        MarketChartSnapshotter,
    )
    assert module.build_chart_snapshotter(
        providers, cache, {"TA_CHART_SNAPSHOT": "0"}
    ) is None
    assert module.chart_snapshot_enabled({"TA_CHART_SNAPSHOT": "1"}) is True


def test_rpt_t11_reader_rejects_damaged_documents(env):
    job_id = _create_job(env)
    root = env.reports.root / job_id
    root.mkdir(parents=True, exist_ok=True)
    damaged = root / "chart_snapshot.json"

    assert env.reports.read_chart_snapshot(job_id) is None
    damaged.write_text("{not json", encoding="utf-8")
    assert env.reports.read_chart_snapshot(job_id) is None
    damaged.write_text(
        json.dumps(
            {
                "schema_version": "chart-snapshot-v2",
                "ticker": "000629",
                "blocks": {"quote": {}},
            }
        ),
        encoding="utf-8",
    )
    assert env.reports.read_chart_snapshot(job_id) is None

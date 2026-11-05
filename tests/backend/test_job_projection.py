"""P2-03 acceptance tests: JobSummary projection and name backfill.

PRJ-01 compares ``job_summary`` with ``job_detail`` field by field, PRJ-02
covers the ticker-name precedence (override > row > directory > null) and
PRJ-03 proves the read path writes no row, changes no ``updated_at`` and adds
no event.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
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

from backend.app.api.v1.serializers import job_detail, job_summary  # noqa: E402
from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent  # noqa: E402
from backend.app.models.stage import STAGE_IDS  # noqa: E402
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.services.ticker_directory import TickerDirectory  # noqa: E402

BACKEND = ROOT / "backend"
TODAY = "2026-11-05"
NOW = datetime(2026, 11, 5, 9, 30, tzinfo=CST)
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
DIRECTORY_NAMES = {"000629": "钒钛股份"}


def _job(**overrides) -> Job:
    values = {
        "id": "job_projection_1",
        "ticker_code": "000629",
        "ticker_name": "钒钛股份",
        "analysis_date": TODAY,
        "status": "running",
        "pending_action": None,
        "config_snapshot": {},
        "config_hash": "hash",
        "graph_version": "graph-v1",
        "idempotency_key": "key",
        "idempotency_body_hash": "body",
        "retry_of_job_id": None,
        "resume_of_job_id": None,
        "resume_from_stage": None,
        "lease_owner": None,
        "lease_expires_at": None,
        "error_code": None,
        "error_message": None,
        "created_at": "2026-11-05T09:00:00+08:00",
        "updated_at": "2026-11-05T09:01:00+08:00",
        "started_at": "2026-11-05T09:00:01+08:00",
        "finished_at": None,
        "report_id": None,
    }
    values.update(overrides)
    return Job(**values)


class _BrokenDirectory:
    def name(self, code: str) -> str | None:
        raise RuntimeError("name directory is down")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")

    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    clock = lambda: NOW  # noqa: E731
    service = JobService(engine, SERVER_CONFIG, clock=clock, reports=reports)
    client = TestClient(
        create_app(
            service=service,
            server_config=SERVER_CONFIG,
            report_store=reports,
        )
    )
    try:
        yield SimpleNamespace(
            engine=engine, service=service, client=client, clock=clock
        )
    finally:
        client.close()
        engine.dispose()


def _create(env) -> str:
    outcome = env.service.create_job(
        {"ticker": "000629", "analysis_date": TODAY, "config": dict(CONFIG)},
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


# PRJ-01 ---------------------------------------------------------------


def test_summary_is_detail_without_stages():
    job = _job()
    stages = {
        STAGE_IDS[0]: {
            "status": "active",
            "started_at": "2026-11-05T09:00:01+08:00",
            "finished_at": None,
            "duration_ms": None,
        }
    }
    kwargs = {"stages": stages, "stats": {"model_calls": 3}, "reconcile_notes": ()}

    detail = job_detail(job, **kwargs)
    summary = job_summary(job, **kwargs)

    assert "stages" not in summary
    assert summary == {key: value for key, value in detail.items() if key != "stages"}
    assert summary["current_stage"] == {
        "id": STAGE_IDS[0],
        "name": detail["stages"][0]["name"],
        "index": 1,
        "total": len(STAGE_IDS),
        "status": "active",
    }
    assert summary["stats"]["model_calls"] == 3


# PRJ-02 ---------------------------------------------------------------


def test_missing_name_is_backfilled_from_the_directory():
    job = _job(ticker_name=None)
    directory = TickerDirectory(DIRECTORY_NAMES, clock=lambda: NOW)
    assert job_detail(job, ticker_directory=directory)["ticker_name"] == "钒钛股份"
    assert job_summary(job, ticker_directory=directory)["ticker_name"] == "钒钛股份"


def test_broken_directory_keeps_the_name_null():
    job = _job(ticker_name=None)
    detail = job_detail(job, ticker_directory=_BrokenDirectory())
    assert detail["ticker_name"] is None


def test_name_precedence_override_then_row_then_directory():
    job = _job(ticker_name="库内名称")
    directory = TickerDirectory(DIRECTORY_NAMES, clock=lambda: NOW)

    assert job_detail(job, ticker_directory=directory)["ticker_name"] == "库内名称"
    assert (
        job_detail(job, ticker_name="调用方覆盖", ticker_directory=directory)[
            "ticker_name"
        ]
        == "调用方覆盖"
    )
    assert (
        job_detail(_job(ticker_name="   "), ticker_directory=directory)["ticker_name"]
        == "钒钛股份"
    )


# PRJ-03 ---------------------------------------------------------------


def _row_and_events(env, job_id: str) -> tuple[tuple, int]:
    with Session(env.engine) as session:
        job = session.get(Job, job_id)
        events = list(
            session.scalars(select(JobEvent).where(JobEvent.job_id == job_id))
        )
        return (
            (job.updated_at, job.status, job.report_id, job.pending_action),
            len(events),
        )


def test_detail_read_writes_nothing(env):
    job_id = _create(env)
    before = _row_and_events(env, job_id)

    first = env.client.get(f"/api/v1/jobs/{job_id}")
    assert first.status_code == 200
    assert first.json()["ticker_name"] is None

    second = env.client.get(f"/api/v1/jobs/{job_id}")
    assert second.status_code == 200
    assert second.json() == first.json()

    assert _row_and_events(env, job_id) == before

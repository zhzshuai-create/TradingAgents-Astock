"""P2-04 acceptance tests: GET /api/v1/jobs (LST-01 .. LST-06).

Rows are inserted directly so each test controls ``created_at``, ``status`` and
``analysis_date`` without touching the write paths. Every test is a read:
LST-05 snapshots all job, stage and event rows around the calls.
"""

from __future__ import annotations

import sys
from datetime import datetime
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

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobIdempotencyKey  # noqa: E402
from backend.app.models.job import JOB_STATUSES  # noqa: E402
from backend.app.models.stage import JobStage  # noqa: E402
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.services.ticker_directory import TickerDirectory  # noqa: E402

BACKEND = ROOT / "backend"
NOW = datetime(2026, 11, 5, 9, 30, tzinfo=CST)
SERVER_CONFIG = ServerConfig(write_mode="next")
DIRECTORY_NAMES = {"000629": "钒钛股份"}

PENDING_BY_STATUS = {
    "pause_requested": "pause",
    "cancel_requested": "cancel",
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")

    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    service = JobService(engine, SERVER_CONFIG, clock=lambda: NOW, reports=reports)
    directory = TickerDirectory(DIRECTORY_NAMES, clock=lambda: NOW)
    client = TestClient(
        create_app(
            service=service,
            server_config=SERVER_CONFIG,
            report_store=reports,
            ticker_directory=directory,
        )
    )
    try:
        yield SimpleNamespace(engine=engine, service=service, client=client)
    finally:
        client.close()
        engine.dispose()


def _add_job(
    env,
    index: int,
    *,
    job_id: str | None = None,
    status: str = "succeeded",
    ticker: str = "000629",
    ticker_name: str | None = None,
    analysis_date: str = "2026-11-01",
    created_at: str = "2026-11-05T09:00:00+08:00",
) -> str:
    job_id = job_id or f"job_{index:03d}"
    with Session(env.engine) as session:
        session.add(
            Job(
                id=job_id,
                ticker_code=ticker,
                ticker_name=ticker_name,
                analysis_date=analysis_date,
                status=status,
                pending_action=PENDING_BY_STATUS.get(status),
                config_snapshot={},
                config_hash=f"hash-{job_id}",
                graph_version="graph-v1",
                idempotency_key=f"key-{job_id}",
                idempotency_body_hash="body",
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()
    return job_id


def _ids(response) -> list[str]:
    return [item["job_id"] for item in response.json()["items"]]


# LST-01 ---------------------------------------------------------------


def test_default_page_is_twenty_newest_and_stable(env):
    for index in range(25):
        minute = index % 60
        _add_job(
            env,
            index,
            created_at=f"2026-11-05T09:{minute:02d}:00+08:00",
        )

    response = env.client.get("/api/v1/jobs")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 20
    assert body["next_cursor"]

    with Session(env.engine) as session:
        expected = [
            (job.created_at, job.id)
            for job in session.scalars(
                select(Job).order_by(Job.created_at.desc(), Job.id.asc()).limit(20)
            )
        ]
    got = [(item["created_at"], item["job_id"]) for item in body["items"]]
    assert got == expected

    first = body["items"][0]
    assert "stages" not in first
    assert first["links"]["self"] == f"/api/v1/jobs/{first['job_id']}"
    assert first["ticker_name"] == "钒钛股份"


def test_same_second_rows_are_ordered_by_job_id(env):
    stamp = "2026-11-05T09:00:00+08:00"
    for job_id in ("job_c", "job_a", "job_b"):
        _add_job(env, 0, job_id=job_id, created_at=stamp)

    response = env.client.get("/api/v1/jobs")
    assert response.status_code == 200
    assert _ids(response) == ["job_a", "job_b", "job_c"]


# LST-02 ---------------------------------------------------------------


@pytest.mark.parametrize("status", JOB_STATUSES)
def test_active_is_mutually_exclusive_with_status(env, status):
    _add_job(env, 1)

    response = env.client.get(
        "/api/v1/jobs", params={"active": "true", "status": status}
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["field"] == "active"


def test_active_true_returns_only_the_five_open_statuses(env):
    for index, status in enumerate(JOB_STATUSES, 1):
        _add_job(env, index, status=status, ticker=f"{index:06d}")

    response = env.client.get("/api/v1/jobs", params={"active": "true"})
    assert response.status_code == 200
    statuses = {item["status"] for item in response.json()["items"]}
    assert statuses == {
        "queued",
        "running",
        "pause_requested",
        "paused",
        "cancel_requested",
    }


def test_unknown_status_value_is_rejected(env):
    response = env.client.get("/api/v1/jobs", params={"status": "running,nope"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["field"] == "status"
    assert "running" in error["details"]["allowed_values"]


# LST-03 ---------------------------------------------------------------


def test_ticker_and_closed_date_interval(env):
    _add_job(env, 1, job_id="before", ticker="000629", analysis_date="2026-09-30")
    _add_job(env, 2, job_id="from_edge", ticker="000629", analysis_date="2026-10-01")
    _add_job(env, 3, job_id="inside", ticker="000629", analysis_date="2026-10-15")
    _add_job(env, 4, job_id="to_edge", ticker="000629", analysis_date="2026-10-31")
    _add_job(env, 5, job_id="after", ticker="000629", analysis_date="2026-11-01")
    _add_job(env, 6, job_id="other", ticker="600519", analysis_date="2026-10-15")

    response = env.client.get(
        "/api/v1/jobs",
        params={
            "ticker": "000629",
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
        },
    )
    assert response.status_code == 200
    assert sorted(_ids(response)) == ["from_edge", "inside", "to_edge"]


def test_status_filter_accepts_multiple_values(env):
    _add_job(env, 1, status="running", ticker="000001")
    _add_job(env, 2, status="failed", ticker="000002")
    _add_job(env, 3, status="succeeded", ticker="000003")

    response = env.client.get("/api/v1/jobs", params={"status": "running,failed"})
    assert response.status_code == 200
    assert {item["status"] for item in response.json()["items"]} == {
        "running",
        "failed",
    }


# LST-04 ---------------------------------------------------------------


def test_cursor_pages_cover_every_row_once(env):
    for index in range(7):
        stamp = (
            "2026-11-05T09:00:00+08:00"
            if index < 3
            else f"2026-11-05T09:0{index}:00+08:00"
        )
        _add_job(env, index, created_at=stamp)

    expected_ids = _ids(env.client.get("/api/v1/jobs"))

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        response = env.client.get("/api/v1/jobs", params=params)
        assert response.status_code == 200
        body = response.json()
        pages += 1
        seen.extend(_ids(response))
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == len(set(seen)) == 7
    assert seen == expected_ids


# LST-05 ---------------------------------------------------------------


def _snapshot(env):
    with Session(env.engine) as session:
        jobs = sorted(
            (
                job.id,
                job.status,
                job.updated_at,
                job.pending_action,
                job.report_id,
            )
            for job in session.scalars(select(Job))
        )
        counts = {
            "jobs": session.scalar(select(func.count()).select_from(Job)),
            "stages": session.scalar(select(func.count()).select_from(JobStage)),
            "events": session.scalar(select(func.count()).select_from(JobEvent)),
            "keys": session.scalar(select(func.count()).select_from(JobIdempotencyKey)),
        }
    return jobs, counts


def test_list_reads_change_no_row(env):
    _add_job(env, 1, status="running")
    _add_job(env, 2, status="failed", created_at="2026-11-05T08:00:00+08:00")
    before = _snapshot(env)

    first = env.client.get("/api/v1/jobs")
    assert first.status_code == 200
    cursor = first.json()["next_cursor"] or ""
    for params in (
        {},
        {"active": "true"},
        {"status": "failed"},
        {"ticker": "000629", "date_from": "2026-11-01"},
        {"limit": 1},
        {"cursor": cursor} if cursor else {"limit": 1},
    ):
        assert env.client.get("/api/v1/jobs", params=params).status_code == 200

    assert _snapshot(env) == before


# LST-06 ---------------------------------------------------------------


def test_limit_caps_at_one_hundred_and_floors_at_one(env):
    for index in range(101):
        _add_job(env, index, ticker=f"{index:06d}")

    capped = env.client.get("/api/v1/jobs", params={"limit": 500})
    assert capped.status_code == 200
    assert len(capped.json()["items"]) == 100
    assert capped.json()["next_cursor"]

    floored = env.client.get("/api/v1/jobs", params={"limit": 0})
    assert floored.status_code == 200
    assert len(floored.json()["items"]) == 1


@pytest.mark.parametrize("cursor", ["!!!", "bm90LWEtY3Vyc29y", "YWJj"])
def test_invalid_cursor_is_rejected(env, cursor):
    _add_job(env, 1)
    response = env.client.get("/api/v1/jobs", params={"cursor": cursor})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["field"] == "cursor"


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-13-01"},
        {"date_to": "2026/10/01"},
        {"date_from": "2026-10-1"},
        {"date_to": "2099-01-01"},
    ],
)
def test_invalid_date_is_rejected(env, params):
    response = env.client.get("/api/v1/jobs", params=params)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_date"
    assert error["details"]["field"] in ("date_from", "date_to")

"""P6-01 acceptance tests: the single analysis writer switch (WM-01 .. WM-08).

The switch is a process-start value: ``load_server_config()`` reads
``ACTIVE_ANALYSIS_UI`` once, and ``_create_once`` refuses only the step-5 insert.
Replays and existing jobs must still answer, so a client that lost a response
is never told its create failed.
"""

from __future__ import annotations

import copy
import sys
import uuid
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
from backend.app.core.journal_probe import JournalProbe  # noqa: E402
from backend.app.core.server_config import ServerConfig, load_server_config  # noqa: E402
from backend.app.core.write_mode import (  # noqa: E402
    WRITE_MODE_ENV,
    parse_write_mode,
)
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobIdempotencyKey  # noqa: E402
from backend.app.services.job_service import CST, JobService  # noqa: E402

BACKEND = ROOT / "backend"
CLOCK = datetime(2026, 10, 30, 9, 0, tzinfo=CST)
TODAY = "2026-10-30"
CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _config(write_mode: str) -> ServerConfig:
    return ServerConfig(
        graph_version="graph-v1",
        llm_profiles=("deepseek-default", "openai-default"),
        parallel_analysts=True,
        stage_toggles={"policy": True, "hot_money": True, "lockup": True},
        write_mode=write_mode,
    )


def _probe(tmp_path) -> JournalProbe:
    return JournalProbe(
        entry_url="http://127.0.0.1:8522",
        install_dir=tmp_path / "missing-journal",
        connect=lambda host, port, timeout: None,
        health=lambda url, timeout: "ok",
    )


def _env(tmp_path, monkeypatch, write_mode: str):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    command.upgrade(_alembic_config(), "head")

    config = _config(write_mode)
    engine = build_engine()
    service = JobService(engine, config, clock=lambda: CLOCK)
    client = TestClient(
        create_app(
            service=service,
            server_config=config,
            journal_probe=_probe(tmp_path),
        )
    )
    return SimpleNamespace(
        engine=engine, service=service, client=client, config=config
    )


def _body(**overrides) -> dict:
    body = {
        "ticker": "000629",
        "analysis_date": TODAY,
        "config": copy.deepcopy(CONFIG),
    }
    body.update(overrides)
    return body


def _post(env, body: dict, key: str | None = None):
    headers = {"Idempotency-Key": key or str(uuid.uuid4())}
    return env.client.post("/api/v1/jobs", json=body, headers=headers)


def _counts(engine) -> tuple[int, int, int]:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(Job)),
            session.scalar(select(func.count()).select_from(JobEvent)),
            session.scalar(select(func.count()).select_from(JobIdempotencyKey)),
        )


# WM-01 ------------------------------------------------------------------


def test_wm01_defaults_to_legacy(tmp_path, monkeypatch):
    monkeypatch.delenv(WRITE_MODE_ENV, raising=False)
    assert load_server_config().write_mode == "legacy"

    env = _env(tmp_path, monkeypatch, "legacy")
    try:
        response = env.client.get("/api/v1/meta/options")
        assert response.status_code == 200
        assert response.json()["write_mode"] == "legacy"
    finally:
        env.client.close()
        env.engine.dispose()


# WM-02 ------------------------------------------------------------------


def test_wm02_next_mode_creates_a_job(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch, "next")
    try:
        before = _counts(env.engine)
        response = _post(env, _body())
        assert response.status_code == 201
        assert _counts(env.engine) == tuple(count + 1 for count in before)
    finally:
        env.client.close()
        env.engine.dispose()


# WM-03 ------------------------------------------------------------------


def test_wm03_legacy_refuses_a_new_job_without_writing(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch, "legacy")
    try:
        before = _counts(env.engine)
        response = _post(env, _body())

        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "write_mode_legacy"
        assert error["message"] == "当前由旧版发起分析，请到旧版入口开始分析"
        assert error["request_id"] == response.headers["X-Request-Id"]
        assert "details" not in error
        assert _counts(env.engine) == before
    finally:
        env.client.close()
        env.engine.dispose()


# WM-04 ------------------------------------------------------------------


def test_wm04_legacy_still_replays_an_existing_key(tmp_path, monkeypatch):
    writer = _env(tmp_path, monkeypatch, "next")
    try:
        key = str(uuid.uuid4())
        first = _post(writer, _body(), key)
        assert first.status_code == 201
        job_id = first.json()["job_id"]
        before = _counts(writer.engine)
    finally:
        writer.client.close()
        writer.engine.dispose()

    # A second process started in legacy mode shares the same database.
    reader = _env(tmp_path, monkeypatch, "legacy")
    try:
        replay = _post(reader, _body(), key)
        assert replay.status_code == 200
        assert replay.headers["Idempotency-Replayed"] == "1"
        assert replay.json()["job_id"] == job_id
        assert _counts(reader.engine) == before
    finally:
        reader.client.close()
        reader.engine.dispose()


# WM-05 ------------------------------------------------------------------


def test_wm05_illegal_values_refuse_to_start(monkeypatch):
    for raw in ("", "   ", "nextt", "both", "legacy-ui"):
        with pytest.raises(ValueError) as caught:
            parse_write_mode(raw)
        message = str(caught.value)
        assert WRITE_MODE_ENV in message
        assert "legacy" in message and "next" in message

    monkeypatch.setenv(WRITE_MODE_ENV, "LEGACYX")
    with pytest.raises(ValueError):
        load_server_config()

    monkeypatch.setenv(WRITE_MODE_ENV, " Next ")
    assert load_server_config().write_mode == "next"

    monkeypatch.setenv(WRITE_MODE_ENV, "LEGACY")
    assert load_server_config().write_mode == "legacy"


# WM-07 ------------------------------------------------------------------


def test_wm07_legacy_refuses_retry(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch, "next")
    try:
        created = _post(env, _body())
        assert created.status_code == 201
        job_id = created.json()["job_id"]

        with Session(env.engine) as session:
            job = session.get(Job, job_id)
            job.status = "failed"
            job.error_code = "internal_error"
            session.commit()
        before = _counts(env.engine)
    finally:
        env.client.close()
        env.engine.dispose()

    legacy = _env(tmp_path, monkeypatch, "legacy")
    try:
        response = legacy.client.post(
            f"/api/v1/jobs/{job_id}/retry",
            json={"mode": "same_config"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "write_mode_legacy"
        assert _counts(legacy.engine) == before

        detail = legacy.client.get(f"/api/v1/jobs/{job_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "failed"
    finally:
        legacy.client.close()
        legacy.engine.dispose()


# WM-08 ------------------------------------------------------------------


def test_wm08_legacy_reports_active_conflict_before_write_mode(tmp_path, monkeypatch):
    writer = _env(tmp_path, monkeypatch, "next")
    try:
        first = _post(writer, _body())
        assert first.status_code == 201
        active_id = first.json()["job_id"]
    finally:
        writer.client.close()
        writer.engine.dispose()

    legacy = _env(tmp_path, monkeypatch, "legacy")
    try:
        different = _body(
            config={**copy.deepcopy(CONFIG), "parallel_analysts": False}
        )
        response = _post(legacy, different)
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "active_conflict"
        assert error["details"]["active_job_id"] == active_id
    finally:
        legacy.client.close()
        legacy.engine.dispose()

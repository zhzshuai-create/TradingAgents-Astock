"""P2-04 acceptance tests: GET /api/v1/meta/options (META-01 .. META-05).

The journal block is driven by an injected probe, so no test opens a socket.
Every assertion checks the frozen field list from api-v1.md 1.8 and proves the
route stays read-only and free of secrets or absolute paths.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
from backend.app.core.journal_probe import (  # noqa: E402
    DEFAULT_ENTRY_URL,
    ENTRY_URL_ENV,
    INSTALL_DIR_ENV,
    JournalProbe,
)
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobIdempotencyKey  # noqa: E402
from backend.app.models.stage import JobStage  # noqa: E402
from backend.app.services.job_service import JobService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402

BACKEND = ROOT / "backend"
SERVER_CONFIG = ServerConfig()
ENTRY_URL = "http://127.0.0.1:8522"


def _client(tmp_path, monkeypatch, *, probe=None, config=None):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")

    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    server_config = config or SERVER_CONFIG
    service = JobService(engine, server_config, reports=reports)
    client = TestClient(
        create_app(
            service=service,
            server_config=server_config,
            report_store=reports,
            journal_probe=probe
            or JournalProbe(
                entry_url=ENTRY_URL,
                install_dir=tmp_path / "missing-journal",
                connect=lambda host, port, timeout: None,
                health=lambda url, timeout: "ok",
            ),
        )
    )
    return SimpleNamespace(client=client, engine=engine)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    env = _client(tmp_path, monkeypatch)
    try:
        yield env
    finally:
        env.client.close()
        env.engine.dispose()


# META-01 --------------------------------------------------------------


def test_options_has_every_frozen_field(client, monkeypatch):
    from backend.app.api.v1 import meta

    monkeypatch.setattr(
        meta,
        "_now",
        lambda: datetime(2026, 11, 4, 16, 30, tzinfo=timezone.utc),
    )

    response = client.client.get("/api/v1/meta/options")
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {
        "app_version",
        "server_time",
        "default_analysis_date",
        "llm_profiles",
        "stage_toggles",
        "limits",
        "journal",
        "contract_version",
    }
    assert body["app_version"] == "0.9.0"
    assert body["server_time"] == "2026-11-05T00:30:00+08:00"
    assert body["default_analysis_date"] == "2026-11-05"
    assert body["llm_profiles"] == [
        {"id": "deepseek-default", "label": "DeepSeek 默认"}
    ]
    assert body["stage_toggles"] == [
        {"id": "policy", "label": "政策分析", "default": True},
        {"id": "hot_money", "label": "游资追踪", "default": True},
        {"id": "lockup", "label": "解禁监控", "default": True},
    ]
    assert body["limits"] == {"max_active_jobs": 1, "max_date_ahead_days": 0}
    assert body["contract_version"] == "api-v1"


# META-02 --------------------------------------------------------------


def _probe(tmp_path, *, installed, connect, health):
    return JournalProbe(
        entry_url=ENTRY_URL,
        install_dir=tmp_path / ("journal" if installed else "missing-journal"),
        connect=connect,
        health=health,
    )


@pytest.mark.parametrize(
    ("installed", "connect", "health", "available", "reason"),
    [
        (
            True,
            lambda host, port, timeout: None,
            lambda url, timeout: "ok\n",
            True,
            None,
        ),
        (
            True,
            lambda host, port, timeout: (_ for _ in ()).throw(ConnectionRefusedError()),
            lambda url, timeout: "ok",
            False,
            "not_running",
        ),
        (
            False,
            lambda host, port, timeout: (_ for _ in ()).throw(ConnectionRefusedError()),
            lambda url, timeout: "ok",
            False,
            "not_installed",
        ),
        (
            True,
            lambda host, port, timeout: None,
            lambda url, timeout: (_ for _ in ()).throw(OSError("boom")),
            False,
            "probe_failed",
        ),
        (
            True,
            lambda host, port, timeout: (_ for _ in ()).throw(TimeoutError()),
            lambda url, timeout: "ok",
            False,
            "not_running",
        ),
    ],
)
def test_journal_reasons(
    tmp_path, monkeypatch, installed, connect, health, available, reason
):
    install = tmp_path / ("journal" if installed else "missing-journal")
    install.mkdir()
    if installed:
        (install / "run.bat").write_text("python -m streamlit run app.py")

    env = _client(
        tmp_path,
        monkeypatch,
        probe=_probe(tmp_path, installed=installed, connect=connect, health=health),
    )
    try:
        response = env.client.get("/api/v1/meta/options")
        assert response.status_code == 200
        journal = response.json()["journal"]
        assert journal == {
            "available": available,
            "entry_url": ENTRY_URL,
            "reason": reason,
        }
    finally:
        env.client.close()
        env.engine.dispose()


def test_default_journal_entry_url_when_probe_has_no_override(monkeypatch):
    monkeypatch.delenv(ENTRY_URL_ENV, raising=False)
    monkeypatch.delenv(INSTALL_DIR_ENV, raising=False)
    probe = JournalProbe(
        install_dir=Path("does-not-exist"),
        connect=lambda host, port, timeout: (_ for _ in ()).throw(
            ConnectionRefusedError()
        ),
        health=lambda url, timeout: "ok",
    )
    status = probe.probe()
    assert status.entry_url == DEFAULT_ENTRY_URL
    assert status.reason == "not_installed"


def test_probe_failure_never_breaks_the_response(tmp_path, monkeypatch):
    class _Broken:
        def probe(self):
            raise RuntimeError("probe exploded")

    env = _client(tmp_path, monkeypatch, probe=_Broken())
    try:
        response = env.client.get("/api/v1/meta/options")
        assert response.status_code == 200
        body = response.json()
        assert body["journal"]["available"] is False
        assert body["journal"]["reason"] == "probe_failed"
        assert body["contract_version"] == "api-v1"
    finally:
        env.client.close()
        env.engine.dispose()


# META-03 --------------------------------------------------------------


def _counts(engine):
    with Session(engine) as session:
        return {
            "jobs": session.scalar(select(func.count()).select_from(Job)),
            "stages": session.scalar(select(func.count()).select_from(JobStage)),
            "events": session.scalar(select(func.count()).select_from(JobEvent)),
            "keys": session.scalar(select(func.count()).select_from(JobIdempotencyKey)),
        }


def test_options_is_read_only(client):
    before = _counts(client.engine)
    for _ in range(3):
        assert client.client.get("/api/v1/meta/options").status_code == 200
    assert _counts(client.engine) == before


# META-04 --------------------------------------------------------------


def test_options_comes_from_server_config_not_query(tmp_path, monkeypatch):
    config = ServerConfig(
        graph_version="graph-v9",
        llm_profiles=("deepseek-default", "qwen-local"),
        stage_toggles={"policy": False, "lockup": True},
    )
    env = _client(
        tmp_path,
        monkeypatch,
        config=config,
        probe=JournalProbe(
            entry_url=ENTRY_URL,
            install_dir=tmp_path / "missing-journal",
            connect=lambda host, port, timeout: None,
            health=lambda url, timeout: "ok",
        ),
    )
    try:
        response = env.client.get(
            "/api/v1/meta/options",
            params={
                "llm_profiles": "evil",
                "stage_toggles": "policy=true",
                "graph_version": "graph-v0",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["llm_profiles"] == [
            {"id": "deepseek-default", "label": "DeepSeek 默认"},
            {"id": "qwen-local", "label": "qwen-local"},
        ]
        assert body["stage_toggles"] == [
            {"id": "policy", "label": "政策分析", "default": False},
            {"id": "lockup", "label": "解禁监控", "default": True},
        ]
    finally:
        env.client.close()
        env.engine.dispose()


# META-05 --------------------------------------------------------------


def test_options_leaks_no_secret_or_absolute_path(client):
    response = client.client.get("/api/v1/meta/options")
    text = json.dumps(response.json(), ensure_ascii=False)
    lowered = text.lower()
    for needle in (
        "api_key",
        "apikey",
        "secret",
        "token",
        "password",
        "authorization",
    ):
        assert needle not in lowered
    for needle in ("c:\\", "c:/", "/home/", "/users/", "~\\", "~/", ".venv"):
        assert needle not in lowered
    assert response.json()["journal"]["entry_url"] == ENTRY_URL

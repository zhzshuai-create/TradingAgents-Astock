"""P1-01 acceptance tests: SQLite connection and migration foundation.

DB-01 empty directory upgrade creates every table.
DB-02 connections carry foreign_keys=ON, journal_mode=wal, busy_timeout > 0.
DB-03 two upgrade/downgrade round trips leave no schema behind; re-upgrade is idempotent.
DB-04 a database pointed at a temp directory never touches the legacy data dir.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV, get_jobs_db_path  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402

BACKEND = ROOT / "backend"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _tables(db_path: Path) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    finally:
        connection.close()
    return {row[0] for row in rows}


def _scalar(db_path: Path, sql: str):
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(sql).fetchone()
    finally:
        connection.close()
    return row[0] if row else None


@pytest.fixture()
def jobs_db(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    return path


def test_db01_upgrade_head_on_empty_directory(jobs_db):
    assert not jobs_db.exists()

    command.upgrade(_alembic_config(), "head")

    assert jobs_db.exists()
    assert _tables(jobs_db) == {
        "alembic_version",
        "job_kernel_meta",
        "jobs",
        "job_stages",
        "job_events",
        "job_idempotency_keys",
        "reports",
        "worker_lease",
        "legacy_imports",
    }
    assert _scalar(jobs_db, "SELECT version_num FROM alembic_version") == "0006"
    assert (
        _scalar(jobs_db, "SELECT value FROM job_kernel_meta WHERE key = 'schema_contract'")
        == "p0-contracts-v1"
    )


def test_db02_connection_pragmas(jobs_db):
    command.upgrade(_alembic_config(), "head")
    engine = build_engine()
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert (
                connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
            )
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() > 0
    finally:
        engine.dispose()


def test_db03_downgrade_and_upgrade_round_trip_twice(jobs_db):
    cfg = _alembic_config()

    for _ in range(2):
        command.upgrade(cfg, "head")
        assert "job_kernel_meta" in _tables(jobs_db)
        command.downgrade(cfg, "base")
        assert _tables(jobs_db) - {"alembic_version"} == set()
        assert _scalar(jobs_db, "SELECT COUNT(*) FROM alembic_version") == 0

    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    assert _tables(jobs_db) == {
        "alembic_version",
        "job_kernel_meta",
        "jobs",
        "job_stages",
        "job_events",
        "job_idempotency_keys",
        "reports",
        "worker_lease",
        "legacy_imports",
    }
    assert _scalar(jobs_db, "SELECT COUNT(*) FROM alembic_version") == 1


def test_db04_temp_path_leaves_legacy_data_dir_untouched(jobs_db):
    legacy_dir = Path.home() / ".tradingagents"
    legacy_db = legacy_dir / "jobs.db"
    before_entries = sorted(p.name for p in legacy_dir.iterdir()) if legacy_dir.exists() else None
    before_stat = legacy_db.stat() if legacy_db.exists() else None

    assert get_jobs_db_path() == jobs_db
    command.upgrade(_alembic_config(), "head")

    assert jobs_db.exists()
    assert legacy_db.exists() == (before_stat is not None)
    if before_stat is not None:
        after_stat = legacy_db.stat()
        assert (after_stat.st_size, after_stat.st_mtime_ns) == (
            before_stat.st_size,
            before_stat.st_mtime_ns,
        )
    after_entries = sorted(p.name for p in legacy_dir.iterdir()) if legacy_dir.exists() else None
    assert after_entries == before_entries


def test_db04_default_path_without_env_override(monkeypatch):
    monkeypatch.delenv(JOBS_DB_ENV, raising=False)
    assert get_jobs_db_path() == Path.home() / ".tradingagents" / "jobs.db"

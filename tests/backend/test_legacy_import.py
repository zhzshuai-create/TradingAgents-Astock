"""P3-02 acceptance tests: legacy import and its idempotency ledger.

IMP-01: scanning the same five files twice changes neither table.
IMP-02: changing one file's sections adds exactly one report and one ledger row.
IMP-03: forced legacy values, null job_id, and no jobs/job_events rows.
IMP-04: ticker and analysis date come from the path, not the JSON.
IMP-05: losing the ledger primary-key race is a skip, not an exception.
IMP-06: dry run creates no database or file and lists imports/skips.

The repository has one legacy-input fixture (``legacy_report_v1.json``); the
"five golden samples" are five copies of it at different ticker/date paths, as
the legacy runner would have written them. Nothing here reads the real
``~/.tradingagents`` tree.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_legacy_import.py -q
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.models import Job, JobEvent, LegacyImport, Report  # noqa: E402
from backend.app.services.job_service import CST  # noqa: E402
from backend.app.services.legacy_import_service import (  # noqa: E402
    IMPORTED,
    SKIPPED,
    WOULD_IMPORT,
    run_import,
    scan_legacy_files,
)

BACKEND = ROOT / "backend"
FIXTURE = ROOT / "tests" / "fixtures" / "upgrade" / "legacy_report_v1.json"
CLOCK = datetime(2026, 11, 6, 10, 0, tzinfo=CST)
SAMPLES = (
    ("000629", "2026-10-20"),
    ("600519", "2026-10-21"),
    ("000001", "2026-10-22"),
    ("300750", "2026-10-23"),
    ("601318", "2026-10-24"),
)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(db_path))
    command.upgrade(_alembic_config(), "head")
    engine = build_engine()
    try:
        yield SimpleNamespace(
            engine=engine,
            db_path=db_path,
            tmp_path=tmp_path,
            root=tmp_path / "legacy",
        )
    finally:
        engine.dispose()


def _legacy() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write(root: Path, ticker: str, analysis_date: str, data: dict | None = None) -> Path:
    path = (
        root
        / ticker
        / "TradingAgentsStrategy_logs"
        / f"full_states_log_{analysis_date}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _legacy() if data is None else data
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _seed(root: Path) -> list[Path]:
    return [_write(root, ticker, day) for ticker, day in SAMPLES]


def _counts(engine) -> tuple[int, int]:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(Report)),
            session.scalar(select(func.count()).select_from(LegacyImport)),
        )


def _jobs_counts(engine) -> tuple[int, int]:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(Job)),
            session.scalar(select(func.count()).select_from(JobEvent)),
        )


def test_imp01_rescan_adds_nothing(env):
    _seed(env.root)
    first = run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)
    assert first.counts() == {"imported": 5, "would_import": 0, "skipped": 0, "invalid": 0}
    assert _counts(env.engine) == (5, 5)

    second = run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)
    assert second.counts() == {"imported": 0, "would_import": 0, "skipped": 5, "invalid": 0}
    assert all(entry.status == SKIPPED for entry in second.entries)
    assert _counts(env.engine) == (5, 5)


def test_imp02_changed_file_adds_one_report_and_one_ledger_row(env):
    paths = _seed(env.root)
    run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)
    with Session(env.engine) as session:
        before = {
            row.report_id: row.content_hash
            for row in session.scalars(select(Report))
        }

    changed = _legacy()
    changed["final_trade_decision"] += "\n\n补充一段新的决策正文。"
    paths[2].write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

    summary = run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)
    assert summary.counts()["imported"] == 1
    assert summary.counts()["skipped"] == 4
    assert _counts(env.engine) == (6, 6)

    with Session(env.engine) as session:
        after = {row.report_id: row.content_hash for row in session.scalars(select(Report))}
    assert set(before) < set(after)
    assert before.items() <= after.items()
    new_ids = set(after) - set(before)
    assert len(new_ids) == 1


def test_imp03_forced_values_and_no_job(env):
    _seed(env.root)
    run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)
    assert _jobs_counts(env.engine) == (0, 0)

    with Session(env.engine) as session:
        rows = list(session.scalars(select(Report)))
    assert len(rows) == 5
    for row in rows:
        assert row.job_id is None
        assert row.generated_at is None
        assert row.generated_at_source == "unknown"
        assert row.origin == "legacy_import"
        assert row.data_quality_status == "absent"
        assert row.chart_snapshot_status == "none"
        assert row.schema_version == "report-v1"
        assert row.created_at == CLOCK.isoformat(timespec="seconds")
        assert row.payload["meta"]["job_id"] is None
        assert row.payload["meta"]["generated_at"] is None
        assert row.payload["meta"]["generated_at_source"] == "unknown"
        assert row.payload["meta"]["origin"] == "legacy_import"
        assert row.payload["meta"]["data_quality_status"] == "absent"
        assert row.payload["meta"]["chart_snapshot_status"] == "none"
        assert row.payload["meta"]["content_hash"] == row.content_hash


def test_imp04_ticker_and_date_come_from_the_path(env):
    paths = _seed(env.root)
    os.utime(paths[0], (0, 0))
    run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)

    with Session(env.engine) as session:
        rows = list(session.scalars(select(Report)))
    by_ticker = {(row.ticker_code, row.analysis_date): row for row in rows}
    assert set(by_ticker) == set(SAMPLES)
    for ticker, day in SAMPLES:
        row = by_ticker[(ticker, day)]
        assert row.payload["meta"]["ticker_code"] == ticker
        assert row.payload["meta"]["analysis_date"] == day
        assert row.generated_at is None

    sources = {str(entry.path) for entry in scan_legacy_files(env.root)}
    assert sources == {str(path) for path in paths}


def test_imp05_primary_key_race_is_a_skip(env, monkeypatch):
    _seed(env.root)
    run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)
    before = _counts(env.engine)

    real_get = Session.get

    def racing_get(self, entity, ident, **kwargs):
        if entity is LegacyImport:
            return None
        return real_get(self, entity, ident, **kwargs)

    monkeypatch.setattr(Session, "get", racing_get)
    summary = run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)

    assert summary.counts()["imported"] == 0
    assert summary.counts()["skipped"] == 5
    assert {entry.reason for entry in summary.entries} == {"duplicate"}
    assert _counts(env.engine) == before


def test_imp06_dry_run_writes_nothing(env):
    _seed(env.root)
    before_files = {
        path: path.stat().st_mtime_ns for path in env.root.rglob("*.json")
    }
    missing_db = env.tmp_path / "never" / "jobs.db"

    summary = run_import(env.root, apply=False, ledger=set())
    assert summary.mode == "dry-run"
    assert summary.counts() == {"imported": 0, "would_import": 5, "skipped": 0, "invalid": 0}
    assert not missing_db.exists()
    assert not (env.tmp_path / "never").exists()

    run_import(env.root, apply=True, engine=env.engine, clock=lambda: CLOCK)
    with Session(env.engine) as session:
        ledger = {
            (row.source_path, row.content_hash)
            for row in session.scalars(select(LegacyImport))
        }
    before = _counts(env.engine)
    after = run_import(env.root, apply=False, ledger=ledger)
    assert after.counts()["skipped"] == 5
    assert _counts(env.engine) == before
    assert before_files == {
        path: path.stat().st_mtime_ns for path in env.root.rglob("*.json")
    }


def test_cli_default_is_dry_run_and_creates_no_database(env):
    _seed(env.root)
    db_path = env.tmp_path / "cli" / "jobs.db"
    environment = dict(os.environ)
    environment[JOBS_DB_ENV] = str(db_path)
    environment["HOME"] = str(env.tmp_path / "home")
    environment["USERPROFILE"] = str(env.tmp_path / "home")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "import_legacy_reports.py"),
            "--root",
            str(env.root),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["counts"][WOULD_IMPORT] == 5
    assert payload["counts"][IMPORTED] == 0
    assert not db_path.exists()
    assert not db_path.parent.exists()

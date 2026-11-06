"""P1-02 acceptance tests: jobs, job_stages and job_events constraints.

DB-05 status accepts exactly the nine frozen statuses.
DB-06 duplicate (job_id, seq) rejected; audit rows keep seq NULL and may repeat.
DB-07 deleting a job cascades to stages and events.
DB-08 downgrade to 0001 removes every later table.

DB-09 and DB-10 are new ids for constraints this ticket introduces ahead of
P1-04: the partial unique active-fingerprint index and the enum CHECKs.
SM-01 proves a queued row plus its `created` audit record can be persisted.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.models import Job, JobEvent, JobStage  # noqa: E402
from backend.app.models.job import ACTIVE_STATUSES, JOB_STATUSES  # noqa: E402

BACKEND = ROOT / "backend"
TS = "2026-10-30T09:00:00+08:00"


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


@pytest.fixture()
def jobs_db_path(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    return path


@pytest.fixture()
def engine(jobs_db_path):
    command.upgrade(_alembic_config(), "head")
    built = build_engine()
    try:
        yield built
    finally:
        built.dispose()


def _job_row(**overrides) -> dict:
    data = {
        "id": str(uuid.uuid4()),
        "ticker_code": "000629",
        "analysis_date": "2026-10-29",
        "status": "queued",
        "config_snapshot": {"model": "fake", "stage_toggles": {}},
        "config_hash": "a" * 64,
        "graph_version": "fake-graph-v1",
        "idempotency_key": str(uuid.uuid4()),
        "idempotency_body_hash": "b" * 64,
        "created_at": TS,
        "updated_at": TS,
    }
    data.update(overrides)
    return data


def _insert_job(engine, **overrides) -> str:
    row = _job_row(**overrides)
    with Session(engine) as session:
        session.add(Job(**row))
        session.commit()
    return row["id"]


def _insert_event(engine, job_id: str, seq: int | None, event_type: str) -> None:
    with Session(engine) as session:
        session.add(
            JobEvent(
                job_id=job_id,
                seq=seq,
                type=event_type,
                payload={"status": "queued"},
                created_at=TS,
            )
        )
        session.commit()


def test_db05_status_accepts_nine_and_rejects_tenth(engine):
    for index, status in enumerate(JOB_STATUSES):
        _insert_job(engine, ticker_code=f"{index:06d}", status=status)

    with Session(engine) as session:
        assert session.scalar(select(Job).where(Job.status == "interrupted")) is not None

    with pytest.raises(IntegrityError):
        _insert_job(engine, ticker_code="999999", status="retrying")


def test_db06_duplicate_seq_rejected_but_audit_rows_repeat(engine):
    job_id = _insert_job(engine)
    _insert_event(engine, job_id, 1, "status_changed")
    _insert_event(engine, job_id, 2, "stage_changed")

    with pytest.raises(IntegrityError):
        _insert_event(engine, job_id, 2, "stage_changed")

    _insert_event(engine, job_id, None, "reconcile_note")
    _insert_event(engine, job_id, None, "reconcile_note")
    with Session(engine) as session:
        audit_rows = session.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.seq.is_(None))
        ).all()
        assert len(audit_rows) == 2


def test_db07_deleting_job_cascades_to_stages_and_events(engine):
    job_id = _insert_job(engine)
    with Session(engine) as session:
        session.add_all(
            [
                JobStage(job_id=job_id, stage_id="market", status="done"),
                JobStage(job_id=job_id, stage_id="news", status="active"),
            ]
        )
        session.commit()
    _insert_event(engine, job_id, 1, "status_changed")
    _insert_event(engine, job_id, None, "created")

    with Session(engine) as session:
        session.execute(delete(Job).where(Job.id == job_id))
        session.commit()

    with Session(engine) as session:
        assert session.scalars(select(JobStage).where(JobStage.job_id == job_id)).all() == []
        assert session.scalars(select(JobEvent).where(JobEvent.job_id == job_id)).all() == []


def test_db08_downgrade_to_0001_removes_later_tables(jobs_db_path):
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    assert _tables(jobs_db_path) == {
        "alembic_version",
        "job_kernel_meta",
        "jobs",
        "job_stages",
        "job_events",
        "job_idempotency_keys",
        "worker_lease",
        "reports",
        "legacy_imports",
        "report_exports",
    }

    command.downgrade(cfg, "0001")
    assert _tables(jobs_db_path) == {"alembic_version", "job_kernel_meta"}

    command.upgrade(cfg, "head")
    assert "jobs" in _tables(jobs_db_path)


def test_db09_active_fingerprint_partial_unique_index(engine):
    first_id = _insert_job(engine, ticker_code="000001", config_hash="c" * 64)

    with pytest.raises(IntegrityError):
        _insert_job(engine, ticker_code="000001", config_hash="c" * 64)

    _insert_job(engine, ticker_code="000001", config_hash="d" * 64)

    with Session(engine) as session:
        job = session.get(Job, first_id)
        job.status = "succeeded"
        session.commit()

    _insert_job(engine, ticker_code="000001", config_hash="c" * 64)

    assert set(ACTIVE_STATUSES) == {
        "queued",
        "running",
        "pause_requested",
        "paused",
        "cancel_requested",
    }


def test_db10_event_type_and_stage_enums_are_enforced(engine):
    job_id = _insert_job(engine)

    with pytest.raises(IntegrityError):
        _insert_event(engine, job_id, 1, "snapshot")
    with pytest.raises(IntegrityError):
        _insert_event(engine, job_id, 1, "unknown_event")

    _insert_event(engine, job_id, 1, "stage_changed")

    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(JobStage(job_id=job_id, stage_id="unknown", status="pending"))
            session.commit()
    with pytest.raises(IntegrityError):
        with Session(engine) as session:
            session.add(JobStage(job_id=job_id, stage_id="market", status="unknown"))
            session.commit()

    with Session(engine) as session:
        session.add(JobStage(job_id=job_id, stage_id="market", status="skipped"))
        session.commit()


def test_sm01_created_job_is_queued_with_created_audit(engine):
    job_id = _insert_job(engine, status="queued")
    _insert_event(engine, job_id, None, "created")

    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "queued"
        audit = session.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.type == "created")
        ).one()
        assert audit.seq is None

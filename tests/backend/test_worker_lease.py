"""P1-05 acceptance tests: single-row worker lease and job claim.

SM-02: T02 claim flips queued to running and writes the per-job lease fields.
CB-01: B1 crash (queued, never claimed) is reclaimed exactly once on restart
       without creating a second job.
WK-01: a second worker gets no lease and claims nothing.
WK-02: the heartbeat renews expires_at on its fixed interval.
WK-03: an expired job lease is not re-claimed; a running row stays running
       until P1-10 reconciliation, per the no-auto-rerun rule.

The lease row itself is seeded by migration 0004; acquire/heartbeat/release
are compare-and-swap, so only the owner can renew or give it up.
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.models import Job, JobEvent, WorkerLease  # noqa: E402
from backend.app.models.worker_lease import LEASE_ROW_ID  # noqa: E402
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402

BACKEND = ROOT / "backend"
TODAY = "2026-10-30"
SHORT_TTL = timedelta(milliseconds=200)
FAST_HEARTBEAT = timedelta(milliseconds=20)
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


class FakeClock:
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

    clock = FakeClock(datetime(2026, 10, 30, 9, 0, tzinfo=CST))
    engine = build_engine()
    jobs = JobService(engine, SERVER_CONFIG, clock=clock)
    try:
        yield SimpleNamespace(
            engine=engine,
            jobs=jobs,
            clock=clock,
            db_path=path,
            reports=ReportStore(tmp_path / "reports"),
            lease=lambda **kwargs: LeaseService(engine, clock=clock, **kwargs),
        )
    finally:
        engine.dispose()


def _create_job(env, ticker: str = "000629") -> str:
    outcome = env.jobs.create_job(
        {
            "ticker": ticker,
            "analysis_date": TODAY,
            "config": dict(CONFIG),
        },
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def _job(env, job_id: str) -> Job:
    with Session(env.engine) as session:
        return session.get(Job, job_id)


def _lease_row(env) -> WorkerLease:
    with Session(env.engine) as session:
        return session.get(WorkerLease, LEASE_ROW_ID)


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_sm02_claim_writes_running_and_lease_fields(env):
    job_id = _create_job(env)
    lease = env.lease(ttl=timedelta(seconds=30))
    assert lease.acquire("worker-a")

    claimed = lease.claim_next_job("worker-a")

    assert claimed is not None
    assert claimed.id == job_id
    row = _job(env, job_id)
    assert row.status == "running"
    assert row.started_at == "2026-10-30T09:00:00+08:00"
    assert row.updated_at == "2026-10-30T09:00:00+08:00"
    assert row.lease_owner == "worker-a"
    assert row.lease_expires_at == "2026-10-30T09:00:30.000+08:00"

    assert lease.claim_next_job("worker-a") is None
    with Session(env.engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_cb01_b1_restart_reclaims_queued_job_once_without_new_job(env):
    key = str(uuid.uuid4())
    body = {"ticker": "000629", "analysis_date": TODAY, "config": dict(CONFIG)}
    created = env.jobs.create_job(body, idempotency_key=key)
    assert created.status_code == 201
    job_id = created.job.id
    assert _job(env, job_id).status == "queued"

    restarted = env.lease(ttl=timedelta(seconds=30))
    assert restarted.acquire("worker-after-crash")
    claimed = restarted.claim_next_job("worker-after-crash")

    assert claimed is not None and claimed.id == job_id
    assert _job(env, job_id).status == "running"
    assert restarted.claim_next_job("worker-after-crash") is None

    replay = env.jobs.create_job(body, idempotency_key=key)
    assert replay.status_code == 200
    assert replay.job.id == job_id
    with Session(env.engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1
        created_events = session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.type == "created")
        )
        assert created_events == 1


def test_wk01_second_worker_cannot_acquire_lease_or_claim(env):
    job_id = _create_job(env)
    first = Worker(
        env.lease(), jobs=env.jobs, reports=env.reports, owner="worker-1"
    )
    second = Worker(
        env.lease(), jobs=env.jobs, reports=env.reports, owner="worker-2"
    )
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        assert second.claim() is None
        assert _job(env, job_id).status == "queued"

        claimed = first.claim()
        assert claimed is not None and claimed.id == job_id
        assert _lease_row(env).owner == "worker-1"
    finally:
        first.shutdown()
        second.shutdown()

    assert _lease_row(env).owner is None
    assert second.acquire() is True
    try:
        assert second.claim() is None
    finally:
        second.shutdown()


def test_wk02_heartbeat_renews_expiry_on_interval(env):
    lease = env.lease(ttl=timedelta(seconds=2))
    worker = Worker(
        lease,
        jobs=env.jobs,
        reports=env.reports,
        owner="worker-hb",
        heartbeat_interval=timedelta(milliseconds=50),
    )
    try:
        assert worker.acquire() is True
        assert _lease_row(env).expires_at == "2026-10-30T09:00:02.000+08:00"

        env.clock.advance(seconds=1)
        assert _wait_until(
            lambda: _lease_row(env).expires_at == "2026-10-30T09:00:03.000+08:00"
        ), _lease_row(env).expires_at
        assert worker.lost is False
    finally:
        worker.shutdown()


def test_wk03_expired_job_lease_is_not_reclaimed(env):
    job_id = _create_job(env)
    lease = env.lease(ttl=SHORT_TTL)
    assert lease.acquire("dead-worker")
    assert lease.claim_next_job("dead-worker") is not None
    claimed_row = _job(env, job_id)
    assert claimed_row.status == "running"
    assert claimed_row.lease_owner == "dead-worker"

    env.clock.advance(seconds=1)

    successor = env.lease()
    assert successor.acquire("worker-next") is True
    assert successor.claim_next_job("worker-next") is None

    row = _job(env, job_id)
    assert row.status == "running"
    assert row.lease_owner == "dead-worker"
    assert row.lease_expires_at == "2026-10-30T09:00:00.200+08:00"
    with Session(env.engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_claim_requires_the_global_lease(env):
    job_id = _create_job(env)
    lease = env.lease()
    assert lease.claim_next_job("nobody") is None
    assert _job(env, job_id).status == "queued"


def test_claim_takes_one_oldest_queued_job_per_call(env):
    first_id = _create_job(env, "000001")
    env.clock.advance(seconds=1)
    second_id = _create_job(env, "000002")
    env.clock.advance(seconds=1)
    third_id = _create_job(env, "000003")

    lease = env.lease()
    assert lease.acquire("worker-1")

    assert lease.claim_next_job("worker-1").id == first_id
    assert lease.claim_next_job("worker-1").id == second_id
    assert lease.claim_next_job("worker-1").id == third_id
    assert lease.claim_next_job("worker-1") is None

    statuses = [_job(env, job_id).status for job_id in (first_id, second_id, third_id)]
    assert statuses == ["running", "running", "running"]


def test_heartbeat_and_release_ignore_other_owners(env):
    lease = env.lease()
    assert lease.acquire("owner-a")

    assert lease.heartbeat("owner-b") is False
    assert lease.release("owner-b") is False
    assert lease.holds("owner-a") is True
    assert _lease_row(env).owner == "owner-a"

    assert lease.heartbeat("owner-a") is True
    assert lease.release("owner-a") is True
    assert _lease_row(env).owner is None
    assert lease.holds("owner-a") is False


def test_expired_global_lease_can_be_taken_over(env):
    lease = env.lease(ttl=SHORT_TTL)
    assert lease.acquire("dead-worker")
    env.clock.advance(seconds=1)

    next_worker = env.lease()
    assert next_worker.acquire("worker-next") is True
    assert next_worker.holds("worker-next") is True
    assert _lease_row(env).owner == "worker-next"


def test_heartbeat_flags_lost_when_the_lease_moves_away(env):
    lease = env.lease(ttl=timedelta(seconds=30))
    worker = Worker(
        lease,
        jobs=env.jobs,
        reports=env.reports,
        owner="worker-old",
        heartbeat_interval=FAST_HEARTBEAT,
    )
    try:
        assert worker.acquire() is True
        assert lease.release("worker-old") is True
        assert env.lease().acquire("worker-new") is True

        assert _wait_until(lambda: worker.lost is True)
        assert worker.claim() is None
        assert _lease_row(env).owner == "worker-new"
    finally:
        worker.shutdown()


def test_worker_lease_table_is_seeded_with_one_row(env):
    row = _lease_row(env)
    assert row is not None
    assert row.id == LEASE_ROW_ID
    assert row.owner is None
    assert row.expires_at is None

    with pytest.raises(IntegrityError):
        with Session(env.engine) as session:
            session.add(
                WorkerLease(id=2, owner="x", expires_at=None, updated_at=None)
            )
            session.commit()

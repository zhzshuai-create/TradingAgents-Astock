"""Single-worker lease and atomic job claim.

Two layers:

* worker_lease is one row. acquire/heartbeat/release compare-and-swap on
  (owner, expires_at), so a second worker either takes over an expired row or
  loses; it never runs alongside the first.
* jobs.lease_owner / lease_expires_at carry the per-job lease. claim_next_job
  flips exactly one queued row to running with a conditional UPDATE; a lost
  race retries instead of claiming twice.

Expired job leases are never re-claimed here: a running row is not queued, so
it stays running until the P1-10 reconcile turns it into interrupted. That is
the contract's no-auto-rerun rule (job-state-machine.md section 4).

T02 writes its status_changed event in the same transaction as the UPDATE, so
a claimed job always starts its SSE sequence at seq 1.

P1-08 adds two attach-only claims with no status event of their own:

* ``claim_resumed_job`` re-attaches a job the user resumed to running (T09);
  the paused -> running event was already written by the control action.
* ``claim_control_job`` attaches a cancel_requested job that no worker is
  executing (T20 from paused), so the worker can write T13 promptly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from backend.app.models.job import Job
from backend.app.models.worker_lease import LEASE_ROW_ID, WorkerLease
from backend.app.services.event_log import append_event
from backend.app.services.job_service import CST

DEFAULT_LEASE_TTL = timedelta(seconds=30)
DEFAULT_HEARTBEAT_INTERVAL = timedelta(seconds=10)
CLAIM_ATTEMPTS = 3


def _format(moment: datetime) -> str:
    """Lease timestamps keep milliseconds so short test TTLs are visible."""
    return moment.isoformat(timespec="milliseconds")


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class LeaseService:
    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = DEFAULT_LEASE_TTL,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        self._engine = engine
        self._clock = clock or (lambda: datetime.now(CST))
        self._ttl = ttl

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def acquire(self, owner: str) -> bool:
        now = self._clock()
        with Session(self._engine) as session:
            row = session.get(WorkerLease, LEASE_ROW_ID)
            if row is None:
                session.add(
                    WorkerLease(
                        id=LEASE_ROW_ID,
                        owner=owner,
                        expires_at=_format(now + self._ttl),
                        updated_at=_format(now),
                    )
                )
                session.commit()
                return True

            expires = _parse(row.expires_at)
            if row.owner is not None and expires is not None and expires > now:
                return False

            result = session.execute(
                update(WorkerLease)
                .where(
                    WorkerLease.id == LEASE_ROW_ID,
                    WorkerLease.owner.is_not_distinct_from(row.owner),
                    WorkerLease.expires_at.is_not_distinct_from(row.expires_at),
                )
                .values(
                    owner=owner,
                    expires_at=_format(now + self._ttl),
                    updated_at=_format(now),
                )
            )
            session.commit()
            return result.rowcount == 1

    def heartbeat(self, owner: str) -> bool:
        now = self._clock()
        with Session(self._engine) as session:
            result = session.execute(
                update(WorkerLease)
                .where(
                    WorkerLease.id == LEASE_ROW_ID,
                    WorkerLease.owner == owner,
                )
                .values(
                    expires_at=_format(now + self._ttl),
                    updated_at=_format(now),
                )
            )
            session.commit()
            return result.rowcount == 1

    def release(self, owner: str) -> bool:
        now = self._clock()
        with Session(self._engine) as session:
            result = session.execute(
                update(WorkerLease)
                .where(
                    WorkerLease.id == LEASE_ROW_ID,
                    WorkerLease.owner == owner,
                )
                .values(owner=None, expires_at=None, updated_at=_format(now))
            )
            session.commit()
            return result.rowcount == 1

    def holds(self, owner: str) -> bool:
        now = self._clock()
        with Session(self._engine) as session:
            row = session.get(WorkerLease, LEASE_ROW_ID)
            if row is None or row.owner != owner:
                return False
            expires = _parse(row.expires_at)
            return expires is not None and expires > now

    def claim_next_job(self, owner: str) -> Job | None:
        """Claim the oldest queued job, or None. Requires the global lease."""
        if not self.holds(owner):
            return None

        for _ in range(CLAIM_ATTEMPTS):
            now = self._clock()
            now_text = now.isoformat(timespec="seconds")
            with Session(self._engine, expire_on_commit=False) as session:
                candidate = session.scalar(
                    select(Job.id)
                    .where(Job.status == "queued")
                    .order_by(Job.created_at, Job.id)
                    .limit(1)
                )
                if candidate is None:
                    return None

                result = session.execute(
                    update(Job)
                    .where(Job.id == candidate, Job.status == "queued")
                    .values(
                        status="running",
                        started_at=func.coalesce(Job.started_at, now_text),
                        updated_at=now_text,
                        lease_owner=owner,
                        lease_expires_at=_format(now + self._ttl),
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue
                # T02 lives in the same transaction as the UPDATE so a claimed
                # row always has its status_changed event (sse-events-v1.md 3.3).
                append_event(
                    session,
                    job_id=candidate,
                    event_type="status_changed",
                    payload={
                        "from": "queued",
                        "to": "running",
                        "reason": "worker",
                        "detail": None,
                        "pending_action": None,
                        "error": None,
                    },
                    created_at=now_text,
                )
                session.commit()
                return session.get(Job, candidate)
        return None

    def claim_resumed_job(self, owner: str) -> Job | None:
        """Attach a T09 row (running, no lease) without rewriting its status."""
        if not self.holds(owner):
            return None

        for _ in range(CLAIM_ATTEMPTS):
            now = self._clock()
            with Session(self._engine, expire_on_commit=False) as session:
                candidate = session.scalar(
                    select(Job.id)
                    .where(
                        Job.status == "running",
                        Job.lease_owner.is_(None),
                        Job.pending_action.is_(None),
                    )
                    .order_by(Job.updated_at, Job.id)
                    .limit(1)
                )
                if candidate is None:
                    return None

                result = session.execute(
                    update(Job)
                    .where(
                        Job.id == candidate,
                        Job.status == "running",
                        Job.lease_owner.is_(None),
                    )
                    .values(
                        lease_owner=owner,
                        lease_expires_at=_format(now + self._ttl),
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue
                session.commit()
                return session.get(Job, candidate)
        return None

    def claim_control_job(self, owner: str) -> Job | None:
        """Attach a paused-origin cancel_requested row so T13 can finish it."""
        if not self.holds(owner):
            return None

        for _ in range(CLAIM_ATTEMPTS):
            now = self._clock()
            with Session(self._engine, expire_on_commit=False) as session:
                candidate = session.scalar(
                    select(Job.id)
                    .where(
                        Job.status == "cancel_requested",
                        Job.lease_owner.is_(None),
                    )
                    .order_by(Job.updated_at, Job.id)
                    .limit(1)
                )
                if candidate is None:
                    return None

                result = session.execute(
                    update(Job)
                    .where(
                        Job.id == candidate,
                        Job.status == "cancel_requested",
                        Job.lease_owner.is_(None),
                    )
                    .values(
                        lease_owner=owner,
                        lease_expires_at=_format(now + self._ttl),
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue
                session.commit()
                return session.get(Job, candidate)
        return None

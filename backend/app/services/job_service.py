"""Job lifecycle writes: creation, control requests, stage boundaries and stats.

Creation is the single write path for POST /api/v1/jobs and follows
idempotency-conflicts.md section 1. Concurrent creates are decided by the
uniq_active_fingerprint partial index, not by a read-before-write check: a
losing insert retries and re-reads the winner. Every key that resolves to a
job is recorded, including keys that hit step 3 against an already-active
job, so a later replay compares at step 2.

Control actions (P1-08) are accepted asynchronously: pause and cancel write a
pending marker and take effect at the next stage boundary; resume either
re-attaches a live idle worker (T09) or queues the checkpoint (T10). Illegal
requests write a ``transition_rejected`` audit record with ``seq`` NULL, so
the replayable stream stays gapless.

Stage methods commit one boundary at a time (P1-07): the stage row, its
stage_changed event and the cumulative stats event land together, so a crash
can only leave a report file without its done event (B3), never the reverse.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.app.core.server_config import ServerConfig
from backend.app.models.event import JobEvent
from backend.app.models.idempotency import JobIdempotencyKey
from backend.app.models.job import ACTIVE_STATUSES, Job
from backend.app.models.stage import STAGE_IDS, STAGE_NAMES, JobStage
from backend.app.models.worker_lease import LEASE_ROW_ID, WorkerLease
from backend.app.services.config_snapshot import (
    InvalidConfigValue,
    UnknownConfigKey,
    canonical_json,
    config_hash,
    normalize_config,
)
from backend.app.services.event_log import append_event
from backend.app.services.report_store import ReportStore
from backend.app.services.tickers import (
    TickerAmbiguous,
    TickerUnresolved,
    resolve_ticker,
)

CST = timezone(timedelta(hours=8))
MAX_ATTEMPTS = 3
REQUEST_KEYS = ("ticker", "analysis_date", "config")
CONTROL_ACTIONS = ("pause", "resume", "cancel")


class JobCreateError(Exception):
    """A rejected create, carrying the contract error code and safe details."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        field: str | None = None,
        allowed_values: list[str] | None = None,
        candidates: list[dict[str, str]] | None = None,
        active_job_id: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        details = {
            "field": field,
            "allowed_values": allowed_values,
            "candidates": candidates,
            "active_job_id": active_job_id,
        }
        self.details = {key: value for key, value in details.items() if value is not None}


class JobControlError(Exception):
    """A rejected control action, carrying the contract error and details."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code or (404 if code == "job_not_found" else 409)
        self.details = details or {}


@dataclass(frozen=True)
class ControlOutcome:
    status_code: int
    job: Job
    accepted: bool
    action: str
    accepted_at: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CreateOutcome:
    status_code: int
    job: Job
    replayed: bool = False
    existing: bool = False


@dataclass(frozen=True)
class _PreparedCreate:
    ticker_code: str
    analysis_date: str
    body_hash: str
    snapshot: dict[str, Any] = field(repr=False)
    config_hash: str


@dataclass(frozen=True)
class StatsSnapshot:
    model_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed_ms: int = 0

    def as_payload(self) -> dict[str, int]:
        return {
            "model_calls": self.model_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True)
class ReconcileNote:
    code: str
    message: str
    at: str

    def as_payload(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "at": self.at}


@dataclass(frozen=True)
class StageLocation:
    status: str
    report_path: str | None


class JobService:
    def __init__(
        self,
        engine: Engine,
        config: ServerConfig,
        *,
        clock: Callable[[], datetime] | None = None,
        reports: ReportStore | None = None,
    ) -> None:
        self._engine = engine
        self._config = config
        self._clock = clock or (lambda: datetime.now(CST))
        self._reports = reports

    # -- reads ---------------------------------------------------------
    def get_job(self, job_id: str) -> Job | None:
        with Session(self._engine) as session:
            return session.get(Job, job_id)

    # -- create --------------------------------------------------------
    def create_job(
        self, payload: Mapping[str, Any], *, idempotency_key: str
    ) -> CreateOutcome:
        prepared = self._prepare(payload)
        now = self._clock().isoformat(timespec="seconds")

        for _ in range(MAX_ATTEMPTS):
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    outcome = self._create_once(
                        session, prepared, idempotency_key, now
                    )
                    session.commit()
                    return outcome
            except (IntegrityError, OperationalError) as exc:
                if isinstance(exc, OperationalError) and "locked" not in str(exc).lower():
                    raise
                continue
        return self._settle_after_race(prepared, idempotency_key, now)

    def _create_once(
        self,
        session: Session,
        prepared: _PreparedCreate,
        idempotency_key: str,
        now: str,
    ) -> CreateOutcome:
        key_row = session.get(JobIdempotencyKey, idempotency_key)
        if key_row is not None:
            return self._replay(session, key_row, prepared.body_hash)

        active = self._active_job(session, prepared, same_config=True)
        if active is not None:
            return self._existing_outcome(
                session, active, idempotency_key, prepared.body_hash, now
            )

        conflict = self._active_job(session, prepared, same_config=False)
        if conflict is not None:
            if conflict.config_hash == prepared.config_hash:
                # Reads are not one snapshot: the same-config job may have
                # committed between the two SELECTs. Step 3 still wins.
                return self._existing_outcome(
                    session, conflict, idempotency_key, prepared.body_hash, now
                )
            raise JobCreateError("active_conflict", active_job_id=conflict.id)

        job = Job(
            id=str(uuid.uuid4()),
            ticker_code=prepared.ticker_code,
            ticker_name=None,
            analysis_date=prepared.analysis_date,
            status="queued",
            pending_action=None,
            config_snapshot=prepared.snapshot,
            config_hash=prepared.config_hash,
            graph_version=self._config.graph_version,
            idempotency_key=idempotency_key,
            idempotency_body_hash=prepared.body_hash,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        # No ORM relationships are declared, so flush the parent explicitly:
        # job_events and job_idempotency_keys carry FKs to jobs.
        session.flush()
        session.add(
            JobIdempotencyKey(
                idempotency_key=idempotency_key,
                job_id=job.id,
                body_hash=prepared.body_hash,
                created_at=now,
            )
        )
        session.add(
            JobEvent(
                job_id=job.id,
                seq=None,
                type="created",
                payload={"status": "queued"},
                created_at=now,
            )
        )
        return CreateOutcome(201, job)

    def _settle_after_race(
        self,
        prepared: _PreparedCreate,
        idempotency_key: str,
        now: str,
    ) -> CreateOutcome:
        """Re-read after losing every insert attempt; one must be visible now."""
        for _ in range(MAX_ATTEMPTS):
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    key_row = session.get(JobIdempotencyKey, idempotency_key)
                    if key_row is not None:
                        return self._replay(session, key_row, prepared.body_hash)

                    active = self._active_job(session, prepared, same_config=True)
                    if active is not None:
                        outcome = self._existing_outcome(
                            session,
                            active,
                            idempotency_key,
                            prepared.body_hash,
                            now,
                        )
                        session.commit()
                        return outcome

                    conflict = self._active_job(session, prepared, same_config=False)
                    if conflict is not None:
                        if conflict.config_hash == prepared.config_hash:
                            outcome = self._existing_outcome(
                                session,
                                conflict,
                                idempotency_key,
                                prepared.body_hash,
                                now,
                            )
                            session.commit()
                            return outcome
                        raise JobCreateError(
                            "active_conflict", active_job_id=conflict.id
                        )
            except (IntegrityError, OperationalError) as exc:
                if isinstance(exc, OperationalError) and "locked" not in str(exc).lower():
                    raise
                continue
        raise JobCreateError("internal_error")

    def _replay(
        self,
        session: Session,
        key_row: JobIdempotencyKey,
        body_hash: str,
    ) -> CreateOutcome:
        if key_row.body_hash != body_hash:
            raise JobCreateError("idempotency_mismatch")
        job = session.get(Job, key_row.job_id)
        if job is None:
            raise JobCreateError("internal_error")
        return CreateOutcome(200, job, replayed=True)

    def _active_job(
        self,
        session: Session,
        prepared: _PreparedCreate,
        *,
        same_config: bool,
    ) -> Job | None:
        conditions = [
            Job.ticker_code == prepared.ticker_code,
            Job.analysis_date == prepared.analysis_date,
            Job.status.in_(ACTIVE_STATUSES),
        ]
        if same_config:
            conditions.append(Job.config_hash == prepared.config_hash)
        return session.scalars(
            select(Job).where(*conditions).order_by(Job.created_at, Job.id)
        ).first()

    def _existing_outcome(
        self,
        session: Session,
        job: Job,
        idempotency_key: str,
        body_hash: str,
        now: str,
    ) -> CreateOutcome:
        session.add(
            JobIdempotencyKey(
                idempotency_key=idempotency_key,
                job_id=job.id,
                body_hash=body_hash,
                created_at=now,
            )
        )
        return CreateOutcome(200, job, existing=True)

    # -- request validation --------------------------------------------
    def _prepare(self, payload: Mapping[str, Any]) -> _PreparedCreate:
        if not isinstance(payload, Mapping):
            raise JobCreateError("invalid_request", field=None)

        unknown = sorted(set(payload) - set(REQUEST_KEYS))
        if unknown:
            # api-v1.md section 0 requires 422 for non-whitelisted request
            # fields; error-codes-v1.md has no dedicated code for them.
            raise JobCreateError("invalid_request", status_code=422, field=unknown[0])

        ticker_raw = payload.get("ticker")
        if not isinstance(ticker_raw, str) or not ticker_raw.strip():
            raise JobCreateError("invalid_request", field="ticker")

        analysis_date = payload.get("analysis_date")
        if not isinstance(analysis_date, str) or not analysis_date:
            raise JobCreateError("invalid_request", field="analysis_date")
        self._validate_date(analysis_date)

        raw_config = payload.get("config")
        if not isinstance(raw_config, Mapping):
            raise JobCreateError("invalid_request", field="config")

        try:
            ticker_code = resolve_ticker(ticker_raw)
        except TickerUnresolved as exc:
            raise JobCreateError("ticker_unresolved") from exc
        except TickerAmbiguous as exc:
            raise JobCreateError(
                "ticker_ambiguous", candidates=exc.candidates
            ) from exc

        try:
            snapshot = normalize_config(
                raw_config, defaults=self._config.config_defaults()
            )
        except UnknownConfigKey as exc:
            raise JobCreateError("config_unknown_key", field=exc.key) from exc
        except InvalidConfigValue as exc:
            raise JobCreateError("config_invalid_value", field=exc.field) from exc

        if snapshot["llm_profile"] not in self._config.llm_profiles:
            raise JobCreateError(
                "config_invalid_value",
                field="llm_profile",
                allowed_values=list(self._config.llm_profiles),
            )

        body = {
            "ticker": ticker_raw,
            "analysis_date": analysis_date,
            "config": raw_config,
        }
        body_hash = hashlib.sha256(
            canonical_json(body).encode("utf-8")
        ).hexdigest()
        return _PreparedCreate(
            ticker_code=ticker_code,
            analysis_date=analysis_date,
            body_hash=body_hash,
            snapshot=snapshot,
            config_hash=config_hash(snapshot, self._config.graph_version),
        )

    def _validate_date(self, analysis_date: str) -> None:
        try:
            parsed = date.fromisoformat(analysis_date)
        except ValueError as exc:
            raise JobCreateError("invalid_date") from exc
        if parsed.isoformat() != analysis_date:
            raise JobCreateError("invalid_date")
        if parsed > self._clock().astimezone(CST).date():
            raise JobCreateError("invalid_date")

    # -- control actions ------------------------------------------------
    def control(self, job_id: str, action: str) -> ControlOutcome:
        if action == "pause":
            return self.request_pause(job_id)
        if action == "resume":
            return self.request_resume(job_id)
        if action == "cancel":
            return self.request_cancel(job_id)
        raise JobControlError(
            "invalid_request", status_code=400, details={"field": "action"}
        )

    def request_pause(self, job_id: str) -> ControlOutcome:
        """T05: record the pause marker; the worker lands it at a boundary."""
        now = self._now()
        for _ in range(MAX_ATTEMPTS):
            with Session(self._engine, expire_on_commit=False) as session:
                job = session.get(Job, job_id)
                if job is None:
                    raise JobControlError("job_not_found", status_code=404)
                status = job.status
                if status == "pause_requested":
                    return ControlOutcome(
                        200, job, False, "pause", reason="already_pending"
                    )
                if status != "running":
                    rule = {"queued": "I06", "cancel_requested": "I07"}.get(status)
                    self._record_rejection(session, job, "pause", rule, now)
                    raise JobControlError(
                        "illegal_transition",
                        details={"from": status, "action": "pause", "rule": rule},
                    )

                result = session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "running")
                    .values(
                        status="pause_requested",
                        pending_action="pause",
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue
                self._append_status(
                    session,
                    job_id,
                    from_status="running",
                    to_status="pause_requested",
                    reason="user",
                    detail="pause",
                    pending_action="pause",
                    created_at=now,
                )
                session.commit()
                job = session.get(Job, job_id, populate_existing=True)
                return ControlOutcome(202, job, True, "pause", accepted_at=now)
        raise JobControlError("internal_error", status_code=500)

    def request_resume(self, job_id: str) -> ControlOutcome:
        """T09 (worker idle) or T10 (worker busy): resume the same job."""
        now = self._now()
        for _ in range(MAX_ATTEMPTS):
            with Session(self._engine, expire_on_commit=False) as session:
                job = session.get(Job, job_id)
                if job is None:
                    raise JobControlError("job_not_found", status_code=404)
                status = job.status
                if status != "paused":
                    self._record_rejection(session, job, "resume", None, now)
                    raise JobControlError(
                        "illegal_transition",
                        details={"from": status, "action": "resume", "rule": None},
                    )
                if not self._resume_fingerprint_ok(job):
                    raise JobControlError(
                        "resume_fingerprint_mismatch",
                        details={"field": "config_digest"},
                    )

                checkpoint = self._first_unfinished_in(session, job_id)
                target = "running" if self._worker_idle(session) else "queued"
                result = session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "paused")
                    .values(
                        status=target,
                        pending_action=None,
                        resume_from_stage=checkpoint,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue
                self._append_status(
                    session,
                    job_id,
                    from_status="paused",
                    to_status=target,
                    reason="user",
                    detail="resume",
                    pending_action=None,
                    created_at=now,
                )
                session.commit()
                job = session.get(Job, job_id, populate_existing=True)
                return ControlOutcome(202, job, True, "resume", accepted_at=now)
        raise JobControlError("internal_error", status_code=500)

    def request_cancel(self, job_id: str) -> ControlOutcome:
        """T19 (queued, immediate) or T11/T12/T20 (pending, worker lands it)."""
        now = self._now()
        for _ in range(MAX_ATTEMPTS):
            with Session(self._engine, expire_on_commit=False) as session:
                job = session.get(Job, job_id)
                if job is None:
                    raise JobControlError("job_not_found", status_code=404)
                status = job.status
                if status == "cancel_requested":
                    return ControlOutcome(
                        200, job, False, "cancel", reason="already_pending"
                    )
                if status == "queued":
                    result = session.execute(
                        update(Job)
                        .where(Job.id == job_id, Job.status == "queued")
                        .values(
                            status="cancelled",
                            pending_action=None,
                            finished_at=now,
                            lease_owner=None,
                            lease_expires_at=None,
                            updated_at=now,
                        )
                    )
                    if result.rowcount != 1:
                        session.rollback()
                        continue
                    append_event(
                        session,
                        job_id=job_id,
                        event_type="stats",
                        payload=self._latest_stats_payload_in(session, job_id),
                        created_at=now,
                    )
                    self._append_status(
                        session,
                        job_id,
                        from_status="queued",
                        to_status="cancelled",
                        reason="user",
                        detail="cancel",
                        pending_action=None,
                        created_at=now,
                    )
                    session.commit()
                    job = session.get(Job, job_id, populate_existing=True)
                    return ControlOutcome(202, job, True, "cancel", accepted_at=now)
                if status in ("running", "pause_requested", "paused"):
                    result = session.execute(
                        update(Job)
                        .where(Job.id == job_id, Job.status == status)
                        .values(
                            status="cancel_requested",
                            pending_action="cancel",
                            updated_at=now,
                        )
                    )
                    if result.rowcount != 1:
                        session.rollback()
                        continue
                    self._append_status(
                        session,
                        job_id,
                        from_status=status,
                        to_status="cancel_requested",
                        reason="user",
                        detail="cancel",
                        pending_action="cancel",
                        created_at=now,
                    )
                    session.commit()
                    job = session.get(Job, job_id, populate_existing=True)
                    return ControlOutcome(202, job, True, "cancel", accepted_at=now)

                self._record_rejection(session, job, "cancel", None, now)
                raise JobControlError(
                    "illegal_transition",
                    details={"from": status, "action": "cancel", "rule": None},
                )
        raise JobControlError("internal_error", status_code=500)

    def pause_at_boundary(self, job_id: str) -> bool:
        """T06: pause_requested -> paused, releasing the per-job lease."""
        now = self._now()
        with Session(self._engine) as session:
            checkpoint = self._first_unfinished_in(session, job_id)
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "pause_requested")
                .values(
                    status="paused",
                    pending_action=None,
                    resume_from_stage=checkpoint,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            self._append_status(
                session,
                job_id,
                from_status="pause_requested",
                to_status="paused",
                reason="worker",
                detail="pause",
                pending_action=None,
                created_at=now,
            )
            session.commit()
            return True

    def cancel_at_boundary(self, job_id: str) -> bool:
        """T13: cancel_requested -> cancelled; the last stats event precedes it."""
        now = self._now()
        with Session(self._engine) as session:
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "cancel_requested")
                .values(
                    status="cancelled",
                    pending_action=None,
                    finished_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            append_event(
                session,
                job_id=job_id,
                event_type="stats",
                payload=self._latest_stats_payload_in(session, job_id),
                created_at=now,
            )
            self._append_status(
                session,
                job_id,
                from_status="cancel_requested",
                to_status="cancelled",
                reason="worker",
                detail="cancel",
                pending_action=None,
                created_at=now,
            )
            session.commit()
            return True

    def finish_success(
        self, job_id: str, *, detail: str, stats: StatsSnapshot
    ) -> bool:
        """T07/T14: the graph finished while pause/cancel was pending."""
        now = self._now()
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            from_status = job.status
            if from_status not in ("pause_requested", "cancel_requested"):
                return False
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == from_status)
                .values(
                    status="succeeded",
                    pending_action=None,
                    finished_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            append_event(
                session,
                job_id=job_id,
                event_type="stats",
                payload=stats.as_payload(),
                created_at=now,
            )
            self._append_status(
                session,
                job_id,
                from_status=from_status,
                to_status="succeeded",
                reason="worker",
                detail=detail,
                pending_action=None,
                created_at=now,
            )
            session.commit()
            return True

    def job_status(self, job_id: str) -> str | None:
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            return job.status if job is not None else None

    def latest_stats(self, job_id: str) -> StatsSnapshot:
        with Session(self._engine) as session:
            return StatsSnapshot(
                **self._latest_stats_payload_in(session, job_id)
            )

    def first_unfinished_stage(self, job_id: str) -> str | None:
        with Session(self._engine) as session:
            return self._first_unfinished_in(session, job_id)

    def _resume_fingerprint_ok(self, job: Job) -> bool:
        if job.graph_version != self._config.graph_version:
            return False
        return config_hash(job.config_snapshot, job.graph_version) == job.config_hash

    def _worker_idle(self, session: Session) -> bool:
        """A live worker with no running row is idle and can take T09."""
        lease = session.get(WorkerLease, LEASE_ROW_ID)
        if lease is None or not lease.owner or not lease.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(lease.expires_at)
        except ValueError:
            return False
        if expires <= self._clock():
            return False
        busy = session.scalar(
            select(Job.id)
            .where(
                Job.lease_owner == lease.owner,
                Job.status.in_(
                    ("running", "pause_requested", "cancel_requested")
                ),
            )
            .limit(1)
        )
        return busy is None

    def _first_unfinished_in(self, session: Session, job_id: str) -> str | None:
        statuses = {
            row.stage_id: row.status
            for row in session.scalars(
                select(JobStage).where(JobStage.job_id == job_id)
            )
        }
        for stage_id in STAGE_IDS:
            if statuses.get(stage_id) not in ("done", "skipped"):
                return stage_id
        return None

    def _latest_stats_payload_in(
        self, session: Session, job_id: str
    ) -> dict[str, int]:
        event = session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.type == "stats")
            .order_by(JobEvent.id.desc())
            .limit(1)
        ).first()
        if event is None:
            return StatsSnapshot().as_payload()
        return _stats_payload(event.payload)

    def _append_status(
        self,
        session: Session,
        job_id: str,
        *,
        from_status: str,
        to_status: str,
        reason: str,
        detail: str | None,
        pending_action: str | None,
        created_at: str,
    ) -> None:
        append_event(
            session,
            job_id=job_id,
            event_type="status_changed",
            payload={
                "from": from_status,
                "to": to_status,
                "reason": reason,
                "detail": detail,
                "pending_action": pending_action,
                "error": None,
            },
            created_at=created_at,
        )

    def _record_rejection(
        self,
        session: Session,
        job: Job,
        action: str,
        rule: str | None,
        created_at: str,
    ) -> None:
        """Audit-only rejection: seq NULL, not broadcast, status unchanged."""
        append_event(
            session,
            job_id=job.id,
            event_type="transition_rejected",
            payload={
                "from": job.status,
                "action": action,
                "rule": rule,
                "reason": "illegal_transition",
            },
            created_at=created_at,
            broadcast=False,
        )
        session.commit()

    # -- stage persistence ---------------------------------------------
    def start_stage(
        self, job_id: str, stage_id: str, *, index: int, total: int
    ) -> None:
        """Mark one stage active and append its ``started`` event."""
        now = self._now()
        with Session(self._engine) as session:
            row = session.get(JobStage, (job_id, stage_id))
            if row is None:
                row = JobStage(job_id=job_id, stage_id=stage_id)
                session.add(row)
            row.status = "active"
            row.started_at = now
            row.ended_at = None
            row.report_path = None
            append_event(
                session,
                job_id=job_id,
                event_type="stage_changed",
                payload=self._stage_payload(
                    stage_id,
                    "started",
                    index=index,
                    total=total,
                    started_at=now,
                    finished_at=None,
                    duration_ms=None,
                ),
                created_at=now,
            )
            session.commit()

    def finish_stage(
        self,
        job_id: str,
        stage_id: str,
        *,
        index: int,
        total: int,
        stats: StatsSnapshot,
        report_path: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Mark one stage done, then append its ``done`` and ``stats`` events."""
        now = self._now()
        with Session(self._engine) as session:
            row = session.get(JobStage, (job_id, stage_id))
            if row is None:
                raise ValueError(f"stage {stage_id} was never started")
            if duration_ms is None:
                duration_ms = _elapsed_ms(row.started_at, now)
            row.status = "done"
            row.ended_at = now
            row.report_path = report_path
            append_event(
                session,
                job_id=job_id,
                event_type="stage_changed",
                payload=self._stage_payload(
                    stage_id,
                    "done",
                    index=index,
                    total=total,
                    started_at=row.started_at,
                    finished_at=now,
                    duration_ms=duration_ms,
                ),
                created_at=now,
            )
            append_event(
                session,
                job_id=job_id,
                event_type="stats",
                payload=stats.as_payload(),
                created_at=now,
            )
            session.commit()

    def record_stats(self, job_id: str, stats: StatsSnapshot) -> None:
        now = self._now()
        with Session(self._engine) as session:
            append_event(
                session,
                job_id=job_id,
                event_type="stats",
                payload=stats.as_payload(),
                created_at=now,
            )
            session.commit()

    def record_reconcile_note(
        self, job_id: str, *, code: str, message: str
    ) -> ReconcileNote:
        """Audit-only: seq stays NULL so the replayable stream has no gap."""
        now = self._now()
        note = ReconcileNote(code=code, message=message, at=now)
        with Session(self._engine) as session:
            append_event(
                session,
                job_id=job_id,
                event_type="reconcile_note",
                payload=note.as_payload(),
                created_at=now,
                broadcast=False,
            )
            session.commit()
        return note

    def detect_unregistered_stage_outputs(self, job_id: str) -> list[ReconcileNote]:
        """B3 evidence: a stage report file exists but its done event does not.

        P1-07 only detects and describes; P1-10 wires this into the startup
        reconcile that flips the job to interrupted.
        """
        if self._reports is None:
            return []
        files = self._reports.stage_report_paths(job_id)
        if not files:
            return []
        with Session(self._engine) as session:
            rows = {
                row.stage_id: row
                for row in session.scalars(
                    select(JobStage).where(JobStage.job_id == job_id)
                )
            }
            active = {
                stage_id for stage_id, row in rows.items() if row.status == "active"
            }
            done = {
                event.payload.get("stage_id")
                for event in session.scalars(
                    select(JobEvent).where(
                        JobEvent.job_id == job_id,
                        JobEvent.type == "stage_changed",
                    )
                )
                if event.payload.get("stage_status") == "done"
            }
        now = self._now()
        return [
            ReconcileNote(
                code="unregistered_stage_output",
                message=f"发现未登记的阶段产物：{STAGE_NAMES[stage_id]}",
                at=now,
            )
            for stage_id in STAGE_IDS
            if stage_id in files and stage_id not in done and stage_id in active
        ]

    # -- projections ---------------------------------------------------
    def detail_parts(self, job_id: str) -> dict[str, Any]:
        """Stage views, latest stats and reconcile notes for JobDetail."""
        with Session(self._engine) as session:
            stages = self._stage_views(session, job_id)
            latest_stats = session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id, JobEvent.type == "stats")
                .order_by(JobEvent.id.desc())
                .limit(1)
            ).first()
            notes = [
                _note_payload(event.payload)
                for event in session.scalars(
                    select(JobEvent)
                    .where(
                        JobEvent.job_id == job_id,
                        JobEvent.type == "reconcile_note",
                    )
                    .order_by(JobEvent.id)
                )
            ]
            stats = _stats_payload(latest_stats.payload) if latest_stats else None
        return {
            "stages": stages,
            "stats": stats,
            "reconcile_notes": notes,
        }

    def get_stage_location(self, job_id: str, stage_id: str) -> StageLocation | None:
        with Session(self._engine) as session:
            if session.get(Job, job_id) is None:
                return None
            row = session.get(JobStage, (job_id, stage_id))
            if row is None:
                return StageLocation(status="pending", report_path=None)
            return StageLocation(status=row.status, report_path=row.report_path)

    def _stage_views(
        self, session: Session, job_id: str
    ) -> dict[str, dict[str, Any]]:
        rows = {
            row.stage_id: row
            for row in session.scalars(
                select(JobStage).where(JobStage.job_id == job_id)
            )
        }
        durations: dict[str, int | None] = {}
        for event in session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.type == "stage_changed")
            .order_by(JobEvent.id)
        ):
            if event.payload.get("stage_status") == "done":
                durations[event.payload.get("stage_id")] = event.payload.get(
                    "duration_ms"
                )
        views: dict[str, dict[str, Any]] = {}
        for stage_id in STAGE_IDS:
            row = rows.get(stage_id)
            if row is None:
                views[stage_id] = {
                    "status": "pending",
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                }
                continue
            duration = durations.get(stage_id)
            if duration is None and row.status == "done":
                duration = _elapsed_ms(row.started_at, row.ended_at or "")
            views[stage_id] = {
                "status": row.status,
                "started_at": row.started_at,
                "finished_at": row.ended_at,
                "duration_ms": duration,
            }
        return views

    def _stage_payload(
        self,
        stage_id: str,
        stage_status: str,
        *,
        index: int,
        total: int,
        started_at: str | None,
        finished_at: str | None,
        duration_ms: int | None,
    ) -> dict[str, Any]:
        return {
            "stage_id": stage_id,
            "stage_name": STAGE_NAMES[stage_id],
            "stage_status": stage_status,
            "index": index,
            "total": total,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
        }

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")


def _elapsed_ms(started_at: str | None, finished_at: str) -> int:
    if not started_at or not finished_at:
        return 0
    delta = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    return max(0, int(delta.total_seconds() * 1000))


def _stats_payload(payload: Mapping[str, Any]) -> dict[str, int]:
    return {
        key: int(payload.get(key, 0))
        for key in ("model_calls", "tokens_in", "tokens_out", "elapsed_ms")
    }


def _note_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "code": payload.get("code", ""),
        "message": payload.get("message", ""),
        "at": payload.get("at", ""),
    }

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

Terminal writes (P1-09) are once-only via a conditional status UPDATE: the
succeeded path commits the report row, ``jobs.report_id``, the final stats
event, the terminal status event and ``report_ready`` in one transaction; the
failed path marks the still-active stage first and records the error on the
row and in the status event. Retry/resume always creates a new job and never
touches the original.

Startup reconciliation (P1-10) is also a conditional UPDATE: a job in one of
the three worker-held states, or a paused job whose checkpoint artifacts are
gone, becomes ``interrupted`` with one ``status_changed(reconcile)`` event.
B3/B4 audit notes are written in the same transaction (``seq`` NULL). A
succeeded job whose report committed but whose ``report_ready`` did not is the
only case where reconcile appends a broadcast event, and it never changes the
status.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.app.core.server_config import ServerConfig
from backend.app.models.event import JobEvent
from backend.app.models.idempotency import JobIdempotencyKey
from backend.app.models.job import ACTIVE_STATUSES, Job
from backend.app.models.report import Report
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
from backend.app.services.legacy_projection import project_latest
from backend.app.services.report_document import (
    CHART_SNAPSHOT_STATUSES,
    finalize_report,
    report_ready_payload,
)
from backend.app.services.report_store import ReportStore
from backend.app.services.tickers import (
    TickerAmbiguous,
    TickerUnresolved,
    resolve_ticker,
)

CST = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
REQUEST_KEYS = ("ticker", "analysis_date", "config")
CONTROL_ACTIONS = ("pause", "resume", "cancel")
RETRY_MODES = ("same_config", "resume_from_checkpoint")
SAME_CONFIG_RETRYABLE = ("failed", "interrupted", "succeeded")
FINISHABLE_STATUSES = ("running", "pause_requested", "cancel_requested")
INTERRUPTIBLE_STATUSES = (
    "running",
    "pause_requested",
    "cancel_requested",
    "paused",
)
LIST_DEFAULT_LIMIT = 20
LIST_MAX_LIMIT = 100
CURSOR_SEPARATOR = "\x1f"


class InvalidCursor(Exception):
    """An opaque list cursor that cannot be decoded (400 invalid_request)."""


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
        self.details = {
            key: value for key, value in details.items() if value is not None
        }


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
    ticker_name: str | None = None
    retry_of_job_id: str | None = None
    resume_of_job_id: str | None = None
    resume_from_stage: str | None = None


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


@dataclass(frozen=True)
class JobListPage:
    """One page of jobs plus its batch-loaded projection parts."""

    jobs: list[Job]
    views: dict[str, dict[str, dict[str, Any]]]
    stats: dict[str, dict[str, int]]
    notes: dict[str, list[dict[str, str]]]
    next_cursor: str | None


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
    @property
    def engine(self) -> Engine:
        """Shared engine for read-only consumers such as the SSE reader."""
        return self._engine

    def now(self) -> datetime:
        return self._clock()

    def get_job(self, job_id: str) -> Job | None:
        with Session(self._engine) as session:
            return session.get(Job, job_id)

    def list_jobs(
        self,
        *,
        statuses: Sequence[str] = (),
        ticker: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        active: bool = False,
        limit: int = LIST_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> JobListPage:
        """api-v1.md 1.4: read-only, keyset paginated, zero side effects.

        Order is ``created_at DESC, id ASC``; the cursor carries exactly that
        pair so a page boundary can never skip or repeat a row. Stage, stats
        and note projections are batched over the page's ids instead of being
        queried per job.
        """
        conditions = []
        if active:
            conditions.append(Job.status.in_(ACTIVE_STATUSES))
        elif statuses:
            conditions.append(Job.status.in_(list(statuses)))
        if ticker:
            conditions.append(Job.ticker_code == ticker)
        if date_from:
            conditions.append(Job.analysis_date >= date_from)
        if date_to:
            conditions.append(Job.analysis_date <= date_to)

        limit = max(1, min(limit, LIST_MAX_LIMIT))
        after = decode_cursor(cursor) if cursor else None
        with Session(self._engine) as session:
            statement = select(Job).where(*conditions)
            if after is not None:
                created_at, job_id = after
                statement = statement.where(
                    or_(
                        Job.created_at < created_at,
                        and_(
                            Job.created_at == created_at,
                            Job.id > job_id,
                        ),
                    )
                )
            rows = list(
                session.scalars(
                    statement.order_by(Job.created_at.desc(), Job.id.asc()).limit(
                        limit + 1
                    )
                )
            )
            has_more = len(rows) > limit
            jobs = rows[:limit]
            views, stats, notes = self._page_parts(session, [job.id for job in jobs])
        return JobListPage(
            jobs=jobs,
            views=views,
            stats=stats,
            notes=notes,
            next_cursor=(
                encode_cursor(created_at=jobs[-1].created_at, job_id=jobs[-1].id)
                if has_more and jobs
                else None
            ),
        )

    # -- create --------------------------------------------------------
    def create_job(
        self, payload: Mapping[str, Any], *, idempotency_key: str
    ) -> CreateOutcome:
        prepared = self._prepare(payload)
        now = self._clock().isoformat(timespec="seconds")

        for _ in range(MAX_ATTEMPTS):
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    outcome = self._create_once(session, prepared, idempotency_key, now)
                    session.commit()
                    return outcome
            except (IntegrityError, OperationalError) as exc:
                if (
                    isinstance(exc, OperationalError)
                    and "locked" not in str(exc).lower()
                ):
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

        # Step 5 precondition: steps 1-4 still answer a replay or an existing
        # job; only a brand-new job is refused while the legacy UI is the writer.
        if self._config.write_mode == "legacy":
            raise JobCreateError("write_mode_legacy", status_code=409)

        job = Job(
            id=str(uuid.uuid4()),
            ticker_code=prepared.ticker_code,
            ticker_name=prepared.ticker_name,
            analysis_date=prepared.analysis_date,
            status="queued",
            pending_action=None,
            config_snapshot=prepared.snapshot,
            config_hash=prepared.config_hash,
            graph_version=self._config.graph_version,
            idempotency_key=idempotency_key,
            idempotency_body_hash=prepared.body_hash,
            retry_of_job_id=prepared.retry_of_job_id,
            resume_of_job_id=prepared.resume_of_job_id,
            resume_from_stage=prepared.resume_from_stage,
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
                if (
                    isinstance(exc, OperationalError)
                    and "locked" not in str(exc).lower()
                ):
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

    # -- retry / resume ------------------------------------------------
    def retry_job(
        self, job_id: str, *, mode: str, idempotency_key: str
    ) -> CreateOutcome:
        """api-v1.md 1.7: retry/resume always creates a new job, original intact."""
        if mode not in RETRY_MODES:
            raise JobControlError(
                "invalid_request", status_code=400, details={"field": "mode"}
            )
        body_hash = hashlib.sha256(
            canonical_json({"job_id": job_id, "mode": mode}).encode("utf-8")
        ).hexdigest()
        now = self._now()
        for _ in range(MAX_ATTEMPTS):
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    key_row = session.get(JobIdempotencyKey, idempotency_key)
                    if key_row is not None:
                        return self._replay(session, key_row, body_hash)
                    job = session.get(Job, job_id)
                    if job is None:
                        raise JobControlError("job_not_found", status_code=404)
                    prepared = self._prepare_retry(session, job, mode, body_hash)
                    outcome = self._create_once(session, prepared, idempotency_key, now)
                    session.commit()
                    return outcome
            except (IntegrityError, OperationalError) as exc:
                if (
                    isinstance(exc, OperationalError)
                    and "locked" not in str(exc).lower()
                ):
                    raise
                continue
        raise JobCreateError("internal_error")

    def _prepare_retry(
        self,
        session: Session,
        job: Job,
        mode: str,
        body_hash: str,
    ) -> _PreparedCreate:
        if mode == "resume_from_checkpoint":
            if job.status != "interrupted":
                raise JobControlError(
                    "illegal_transition",
                    details={
                        "from": job.status,
                        "action": "resume_from_checkpoint",
                        "rule": None,
                    },
                )
            if not self._resume_fingerprint_ok(job):
                raise JobControlError(
                    "resume_fingerprint_mismatch",
                    details={"field": "config_digest"},
                )
            retry_of: str | None = None
            resume_of: str | None = job.id
            # Reconcile stores the B3-aware point (a stage whose report is on
            # disk counts as finished even without its done row); an
            # interrupted row that predates that scan falls back to stage rows.
            checkpoint = job.resume_from_stage or self._first_unfinished_in(
                session, job.id
            )
        else:
            if job.status not in SAME_CONFIG_RETRYABLE:
                raise JobControlError(
                    "illegal_transition",
                    details={"from": job.status, "action": "retry", "rule": None},
                )
            retry_of = job.id
            resume_of = None
            checkpoint = None

        snapshot = copy.deepcopy(job.config_snapshot)
        return _PreparedCreate(
            ticker_code=job.ticker_code,
            analysis_date=job.analysis_date,
            body_hash=body_hash,
            snapshot=snapshot,
            config_hash=config_hash(snapshot, self._config.graph_version),
            ticker_name=job.ticker_name,
            retry_of_job_id=retry_of,
            resume_of_job_id=resume_of,
            resume_from_stage=checkpoint,
        )

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
            raise JobCreateError("ticker_ambiguous", candidates=exc.candidates) from exc

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
        body_hash = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
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

    def build_success_report(
        self,
        job_id: str,
        report: Mapping[str, Any] | None,
        *,
        chart_snapshot_status: str | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Finalized payload for the pre-commit B4 artifact.

        ``finish_success`` commits the same payload when given this result and
        the same ``generated_at``; finalization is deterministic, so the file
        on disk and the report row cannot disagree about meta or hash.
        """
        if report is None:
            return None
        job = self.get_job(job_id)
        if job is None:
            return None
        return _finalize_success_payload(
            report,
            job,
            generated_at=generated_at or self._now(),
            chart_snapshot_status=chart_snapshot_status,
        )

    def finish_success(
        self,
        job_id: str,
        *,
        detail: str | None,
        stats: StatsSnapshot,
        report: Mapping[str, Any] | None = None,
        chart_snapshot_status: str | None = None,
        generated_at: str | None = None,
    ) -> bool:
        """T03/T07/T14: succeeded once, with its report in the same commit.

        The conditional UPDATE is the write-once gate: a racing cancel
        confirmation (T13) and this commit cannot both land. The report row,
        ``jobs.report_id``, the 13th stats event, the terminal status event and
        ``report_ready`` share one transaction, so B5 can only ever mean "all
        of it is missing", never a half-written report.

        ``chart_snapshot_status`` is the worker's evidence-backed verdict
        (RPT-01). ``None`` keeps the report's own meta so every other caller is
        unchanged; an explicit value overrides a shallow copy, never the
        caller's object. ``generated_at`` pins the report clock to the value
        the worker used for the B4 artifact; ``None`` means now.
        """
        now = generated_at or self._now()
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            from_status = job.status
            ticker_code = job.ticker_code
            analysis_date = job.analysis_date
            if from_status not in FINISHABLE_STATUSES:
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

            ready = None
            if report is not None:
                payload = _finalize_success_payload(
                    report,
                    job,
                    generated_at=now,
                    chart_snapshot_status=chart_snapshot_status,
                )
                meta = payload["meta"]
                session.add(
                    Report(
                        report_id=meta["report_id"],
                        job_id=job_id,
                        ticker_code=job.ticker_code,
                        ticker_name=job.ticker_name,
                        analysis_date=job.analysis_date,
                        generated_at=meta["generated_at"],
                        generated_at_source=meta["generated_at_source"],
                        origin=meta["origin"],
                        schema_version=meta["schema_version"],
                        content_hash=meta["content_hash"],
                        config_digest=meta["config_digest"],
                        data_quality_status=meta["data_quality_status"],
                        chart_snapshot_status=meta["chart_snapshot_status"],
                        retry_of_job_id=job.retry_of_job_id,
                        rating=meta["rating"],
                        signal=meta["signal"],
                        payload=payload,
                        created_at=now,
                    )
                )
                session.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(report_id=meta["report_id"])
                )
                ready = report_ready_payload(payload)

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
            if ready is not None:
                append_event(
                    session,
                    job_id=job_id,
                    event_type="report_ready",
                    payload=ready,
                    created_at=now,
                )
            session.commit()
        if report is not None:
            self._project_legacy(ticker_code, analysis_date)
        return True

    def _project_legacy(self, ticker_code: str, analysis_date: str) -> None:
        """Best-effort old-version projection; never changes the commit result."""
        try:
            project_latest(
                self._engine,
                ticker_code=ticker_code,
                analysis_date=analysis_date,
            )
        except Exception:  # noqa: BLE001 - report stays succeeded
            logger.exception(
                "legacy projection hook failed for %s %s", ticker_code, analysis_date
            )

    def finish_failure(
        self,
        job_id: str,
        *,
        code: str,
        message: str,
        stats: StatsSnapshot,
    ) -> bool:
        """T04/T08/T15: failed once; stage_failed vs post_stage_error.

        A stage still ``active`` when the executor raised is marked failed and
        gets its own stage_changed first. When the exception escaped between
        stages there is no active row, so the detail is ``post_stage_error``.
        """
        now = self._now()
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            from_status = job.status
            if from_status not in FINISHABLE_STATUSES:
                return False
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == from_status)
                .values(
                    status="failed",
                    pending_action=None,
                    finished_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    error_code=code,
                    error_message=message,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                return False

            active = list(
                session.scalars(
                    select(JobStage).where(
                        JobStage.job_id == job_id, JobStage.status == "active"
                    )
                )
            )
            for row in active:
                row.status = "failed"
                row.ended_at = now
                append_event(
                    session,
                    job_id=job_id,
                    event_type="stage_changed",
                    payload=self._stage_payload(
                        row.stage_id,
                        "failed",
                        index=STAGE_IDS.index(row.stage_id) + 1,
                        total=len(STAGE_IDS),
                        started_at=row.started_at,
                        finished_at=now,
                        duration_ms=_elapsed_ms(row.started_at, now),
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
            self._append_status(
                session,
                job_id,
                from_status=from_status,
                to_status="failed",
                reason="worker",
                detail="stage_failed" if active else "post_stage_error",
                pending_action=None,
                created_at=now,
                error={"code": code, "message": message},
            )
            session.commit()
            return True

    def job_status(self, job_id: str) -> str | None:
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            return job.status if job is not None else None

    def latest_stats(self, job_id: str) -> StatsSnapshot:
        with Session(self._engine) as session:
            return StatsSnapshot(**self._latest_stats_payload_in(session, job_id))

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
                Job.status.in_(("running", "pause_requested", "cancel_requested")),
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

    def _latest_stats_payload_in(self, session: Session, job_id: str) -> dict[str, int]:
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
        error: Mapping[str, Any] | None = None,
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
                "error": dict(error) if error is not None else None,
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

    # -- startup reconcile (P1-10) -------------------------------------
    def reconcile_scan(self) -> list[tuple[str, str, str | None]]:
        """All jobs as ``(id, status, resume_from_stage)`` in creation order."""
        with Session(self._engine) as session:
            rows = session.execute(
                select(Job.id, Job.status, Job.resume_from_stage).order_by(
                    Job.created_at, Job.id
                )
            )
            return [(job_id, status, resume) for job_id, status, resume in rows]

    def stage_locations(self, job_id: str) -> dict[str, StageLocation]:
        with Session(self._engine) as session:
            rows = session.scalars(select(JobStage).where(JobStage.job_id == job_id))
            return {
                row.stage_id: StageLocation(
                    status=row.status, report_path=row.report_path
                )
                for row in rows
            }

    def mark_interrupted(
        self,
        job_id: str,
        *,
        detail: str,
        notes: Sequence[ReconcileNote] = (),
        resume_from_stage: str | None = None,
    ) -> bool:
        """T16/T17/T18 and checkpoint loss: status plus one reconcile event.

        The conditional UPDATE is the only deciding write: a row that moved
        since the scan loses and writes nothing, so a live transition is never
        overwritten. Notes are audit records (``seq`` NULL) committed together
        with the status event. Reconcile never runs the graph.
        """
        now = self._now()
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return False
            from_status = job.status
            if from_status not in INTERRUPTIBLE_STATUSES:
                return False
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == from_status)
                .values(
                    status="interrupted",
                    pending_action=None,
                    finished_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    resume_from_stage=resume_from_stage,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                return False
            for note in notes:
                append_event(
                    session,
                    job_id=job_id,
                    event_type="reconcile_note",
                    payload=note.as_payload(),
                    created_at=note.at or now,
                    broadcast=False,
                )
            self._append_status(
                session,
                job_id,
                from_status=from_status,
                to_status="interrupted",
                reason="reconcile",
                detail=detail,
                pending_action=None,
                created_at=now,
            )
            session.commit()
            return True

    def append_report_ready_if_missing(self, job_id: str) -> bool:
        """B5: the report and status committed, the broadcast did not.

        Only appends the event; the status and the report row stay untouched.
        A succeeded job without a report row is left alone rather than
        inventing a payload.
        """
        now = self._now()
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            if job is None or job.status != "succeeded":
                return False
            report = session.scalars(
                select(Report).where(Report.job_id == job_id)
            ).first()
            if report is None:
                return False
            exists = session.scalar(
                select(JobEvent.id)
                .where(
                    JobEvent.job_id == job_id,
                    JobEvent.type == "report_ready",
                )
                .limit(1)
            )
            if exists is not None:
                return False
            append_event(
                session,
                job_id=job_id,
                event_type="report_ready",
                payload=report_ready_payload(report.payload),
                created_at=now,
            )
            session.commit()
            return True

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

    def _stage_views(self, session: Session, job_id: str) -> dict[str, dict[str, Any]]:
        rows = {
            row.stage_id: row
            for row in session.scalars(
                select(JobStage).where(JobStage.job_id == job_id)
            )
        }
        return _stage_views_from(
            rows, _stage_durations(session, [job_id]).get(job_id, {})
        )

    def _page_parts(
        self, session: Session, job_ids: Sequence[str]
    ) -> tuple[
        dict[str, dict[str, dict[str, Any]]],
        dict[str, dict[str, int]],
        dict[str, list[dict[str, str]]],
    ]:
        """Batch projections for one list page: five queries regardless of size."""
        if not job_ids:
            return {}, {}, {}

        rows_by_job: dict[str, dict[str, JobStage]] = {job_id: {} for job_id in job_ids}
        for row in session.scalars(
            select(JobStage).where(JobStage.job_id.in_(job_ids))
        ):
            rows_by_job[row.job_id][row.stage_id] = row
        durations = _stage_durations(session, job_ids)

        stats = {job_id: StatsSnapshot().as_payload() for job_id in job_ids}
        latest = dict(
            session.execute(
                select(JobEvent.job_id, func.max(JobEvent.id))
                .where(
                    JobEvent.job_id.in_(job_ids),
                    JobEvent.type == "stats",
                )
                .group_by(JobEvent.job_id)
            ).all()
        )
        if latest:
            for event in session.scalars(
                select(JobEvent).where(JobEvent.id.in_(latest.values()))
            ):
                stats[event.job_id] = _stats_payload(event.payload)

        notes: dict[str, list[dict[str, str]]] = {job_id: [] for job_id in job_ids}
        for event in session.scalars(
            select(JobEvent)
            .where(
                JobEvent.job_id.in_(job_ids),
                JobEvent.type == "reconcile_note",
            )
            .order_by(JobEvent.id)
        ):
            notes[event.job_id].append(_note_payload(event.payload))

        views = {
            job_id: _stage_views_from(rows_by_job[job_id], durations.get(job_id, {}))
            for job_id in job_ids
        }
        return views, stats, notes

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


def _finalize_success_payload(
    report: Mapping[str, Any],
    job: Job,
    *,
    generated_at: str,
    chart_snapshot_status: str | None,
) -> dict[str, Any]:
    if chart_snapshot_status is not None:
        effective = (
            chart_snapshot_status
            if chart_snapshot_status in CHART_SNAPSHOT_STATUSES
            else "none"
        )
        report = dict(report)
        meta = dict(report.get("meta") or {})
        meta["chart_snapshot_status"] = effective
        report["meta"] = meta
    return finalize_report(
        report,
        job_id=job.id,
        ticker_code=job.ticker_code,
        ticker_name=job.ticker_name,
        analysis_date=job.analysis_date,
        generated_at=generated_at,
        config_digest=job.config_hash,
        retry_of_job_id=job.retry_of_job_id,
    )


def encode_cursor(*, created_at: str, job_id: str) -> str:
    raw = f"{created_at}{CURSOR_SEPARATOR}{job_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """Inverse of :func:`encode_cursor`; raises InvalidCursor on anything else."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidCursor() from exc
    created_at, separator, job_id = raw.partition(CURSOR_SEPARATOR)
    if not separator or not created_at or not job_id:
        raise InvalidCursor()
    return created_at, job_id


def _stage_durations(
    session: Session, job_ids: Sequence[str]
) -> dict[str, dict[str, int | None]]:
    durations: dict[str, dict[str, int | None]] = {job_id: {} for job_id in job_ids}
    for event in session.scalars(
        select(JobEvent)
        .where(
            JobEvent.job_id.in_(job_ids),
            JobEvent.type == "stage_changed",
        )
        .order_by(JobEvent.id)
    ):
        if event.payload.get("stage_status") in ("done", "failed"):
            durations[event.job_id][event.payload.get("stage_id")] = event.payload.get(
                "duration_ms"
            )
    return durations


def _stage_views_from(
    rows: Mapping[str, JobStage],
    durations: Mapping[str, int | None],
) -> dict[str, dict[str, Any]]:
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
        if duration is None and row.status in ("done", "failed"):
            duration = _elapsed_ms(row.started_at, row.ended_at or "")
        views[stage_id] = {
            "status": row.status,
            "started_at": row.started_at,
            "finished_at": row.ended_at,
            "duration_ms": duration,
        }
    return views


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

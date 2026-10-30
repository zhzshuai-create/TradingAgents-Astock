"""Job lifecycle writes: creation, stage boundaries, stats and audit notes.

Creation is the single write path for POST /api/v1/jobs and follows
idempotency-conflicts.md section 1. Concurrent creates are decided by the
uniq_active_fingerprint partial index, not by a read-before-write check: a
losing insert retries and re-reads the winner. Every key that resolves to a
job is recorded, including keys that hit step 3 against an already-active
job, so a later replay compares at step 2.

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

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.app.core.server_config import ServerConfig
from backend.app.models.event import JobEvent
from backend.app.models.idempotency import JobIdempotencyKey
from backend.app.models.job import ACTIVE_STATUSES, Job
from backend.app.models.stage import STAGE_IDS, STAGE_NAMES, JobStage
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

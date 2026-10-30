"""Job creation: the single write path for POST /api/v1/jobs.

The five-step decision order is fixed by idempotency-conflicts.md section 1.
Concurrent creates are decided by the uniq_active_fingerprint partial index,
not by a read-before-write check: a losing insert retries and re-reads the
winner. Every key that resolves to a job is recorded, including keys that hit
step 3 against an already-active job, so a later replay compares at step 2.
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
from backend.app.services.config_snapshot import (
    InvalidConfigValue,
    UnknownConfigKey,
    canonical_json,
    config_hash,
    normalize_config,
)
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


class JobService:
    def __init__(
        self,
        engine: Engine,
        config: ServerConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._config = config
        self._clock = clock or (lambda: datetime.now(CST))

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

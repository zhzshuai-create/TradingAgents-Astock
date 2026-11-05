"""Read-only SSE stream: snapshot, replay and live follow (sse-events-v1.md).

The stream never writes: it reads ``jobs`` and ``job_events`` and nothing else,
so a reconnect cannot create, retry or resume a job (section 7). Worker writes
may land in another process, so live delivery is short polling over SQLite WAL
rather than an in-memory queue. Every frame is generated from the persisted
``seq`` allocator, which means a replay has no holes and an audit row (seq
NULL) never shows up.

Window rule (section 4.3): the last 24 hours, or the last 2000 events,
whichever is shorter. A cursor below the window or beyond the current maximum
is ``sse_cursor_expired``; the client rebuilds from the job detail instead.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.v1.serializers import job_detail
from backend.app.models.event import JobEvent
from backend.app.models.job import TERMINAL_STATUSES, Job
from backend.app.services.job_service import JobService

RETRY_MILLIS = 3000
DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_HEARTBEAT_INTERVAL = 15.0
DEFAULT_RETENTION_HOURS = 24
DEFAULT_RETENTION_COUNT = 2000

PING = ": ping\n\n"


class CursorExpired(Exception):
    """The cursor is outside the replayable window (410 sse_cursor_expired)."""


@dataclass(frozen=True)
class SseFrame:
    event: str
    data: dict[str, Any]
    seq: int | None = None

    def encode(self) -> str:
        # sse-events-v1.md section 2: id, event and one-line JSON data.
        lines = []
        if self.seq is not None:
            lines.append(f"id: {self.seq}")
        lines.append(f"event: {self.event}")
        lines.append(
            "data: "
            + json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        )
        return "\n".join(lines) + "\n\n"


def event_frame(event: dict[str, Any]) -> SseFrame:
    return SseFrame(
        event=event["type"],
        data={
            "seq": event["seq"],
            "job_id": event["job_id"],
            "type": event["type"],
            "at": event["at"],
            "payload": event["payload"],
        },
        seq=event["seq"],
    )


class EventStream:
    def __init__(
        self,
        service: JobService,
        *,
        clock: Callable[[], datetime] | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        retention_hours: float = DEFAULT_RETENTION_HOURS,
        retention_count: int = DEFAULT_RETENTION_COUNT,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._service = service
        self._engine = service.engine
        self._clock = clock or service.now
        self._poll_interval = poll_interval
        self._heartbeat_interval = heartbeat_interval
        self._retention_hours = retention_hours
        self._retention_count = retention_count
        self._monotonic = monotonic
        self._sleep = sleep

    def subscribe(
        self, job: Job, last_event_id: int | None = None
    ) -> Iterator[str]:
        """Validate eagerly, then return the frame generator.

        Raises CursorExpired before any byte is sent; the route turns it into
        410 instead of a half-written 200.
        """
        last_seq = self.max_seq(job.id)
        if last_event_id is not None:
            self._check_cursor(job.id, last_event_id, last_seq)
        return self._stream(job, last_seq, last_event_id)

    def max_seq(self, job_id: str) -> int:
        events = self._broadcast_events(job_id)
        return events[-1]["seq"] if events else 0

    def replay(self, job_id: str, last_event_id: int) -> list[dict[str, Any]]:
        return [
            event
            for event in self._broadcast_events(job_id)
            if event["seq"] > last_event_id
        ]

    def _stream(
        self, job: Job, last_seq: int, cursor: int | None
    ) -> Iterator[str]:
        yield f"retry: {RETRY_MILLIS}\n\n"
        yield self._snapshot(job, last_seq).encode()

        sent = last_seq
        if cursor is not None:
            for event in self.replay(job.id, cursor):
                sent = event["seq"]
                yield event_frame(event).encode()
        status = self._status(job.id)
        if status is None or status in TERMINAL_STATUSES:
            return
        yield from self._follow(job.id, sent)
    def _follow(self, job_id: str, start_seq: int) -> Iterator[str]:
        sent = start_seq
        last_emit = self._monotonic()
        while True:
            events = [
                event for event in self._broadcast_events(job_id)
                if event["seq"] > sent
            ]
            if events:
                for event in events:
                    sent = event["seq"]
                    yield event_frame(event).encode()
                last_emit = self._monotonic()
                continue
            status = self._status(job_id)
            if status is None or status in TERMINAL_STATUSES:
                return
            if self._monotonic() - last_emit >= self._heartbeat_interval:
                yield PING
                last_emit = self._monotonic()
            self._sleep(self._poll_interval)

    def _snapshot(self, job: Job, last_seq: int) -> SseFrame:
        return SseFrame(
            event="snapshot",
            data={
                "seq": last_seq,
                "job_id": job.id,
                "type": "snapshot",
                "at": self._clock().isoformat(timespec="seconds"),
                "payload": {
                    "job": job_detail(
                        job, **self._service.detail_parts(job.id)
                    ),
                    "last_seq": last_seq,
                },
            },
            seq=last_seq,
        )

    def _broadcast_events(self, job_id: str) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(
                    JobEvent.seq, JobEvent.type, JobEvent.payload, JobEvent.created_at
                )
                .where(JobEvent.job_id == job_id, JobEvent.seq.is_not(None))
                .order_by(JobEvent.seq)
            ).all()
        return [
            {
                "seq": int(seq),
                "job_id": job_id,
                "type": event_type,
                "at": created_at,
                "payload": payload,
            }
            for seq, event_type, payload, created_at in rows
        ]

    def _status(self, job_id: str) -> str | None:
        with Session(self._engine) as session:
            job = session.get(Job, job_id)
            return None if job is None else job.status

    def _check_cursor(
        self, job_id: str, cursor: int, max_seq: int
    ) -> None:
        # A cursor past the maximum is not in the contract; treat it like an
        # expired one instead of replaying an empty stream forever.
        if cursor > max_seq:
            raise CursorExpired(cursor)
        window_min = self._window_min(job_id, max_seq)
        if cursor < window_min - 1:
            raise CursorExpired(cursor)

    def _window_min(self, job_id: str, max_seq: int) -> int:
        cutoff = (
            self._clock() - timedelta(hours=self._retention_hours)
        ).timestamp()
        with Session(self._engine) as session:
            rows = session.execute(
                select(JobEvent.seq, JobEvent.created_at).where(
                    JobEvent.job_id == job_id, JobEvent.seq.is_not(None)
                )
            ).all()
        in_window = []
        for seq, created_at in rows:
            epoch = _epoch(created_at)
            if epoch is not None and epoch >= cutoff:
                in_window.append(int(seq))
        count_floor = max_seq - self._retention_count + 1
        if not in_window:
            return max_seq + 1
        return max(count_floor, min(in_window))


def _epoch(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None

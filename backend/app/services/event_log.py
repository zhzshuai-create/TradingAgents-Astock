"""Append-only job events with one allocator for the replayable sequence.

sse-events-v1.md section 3 splits the row types in two: the five broadcast
types consume a ``seq`` starting at 1 with no gaps, while ``created``,
``transition_rejected`` and ``reconcile_note`` are audit records with
``seq = NULL`` so they never punch holes into replay.

Allocation is MAX(seq) + 1 inside the writer's own transaction. The single
worker lease serializes writers; ``UNIQUE(job_id, seq)`` is the backstop if a
second writer ever appears.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.event import JobEvent


def next_seq(session: Session, job_id: str) -> int:
    current = session.scalar(
        select(func.max(JobEvent.seq)).where(JobEvent.job_id == job_id)
    )
    return (current or 0) + 1


def append_event(
    session: Session,
    *,
    job_id: str,
    event_type: str,
    payload: dict[str, Any],
    created_at: str,
    broadcast: bool = True,
) -> JobEvent:
    event = JobEvent(
        job_id=job_id,
        seq=next_seq(session, job_id) if broadcast else None,
        type=event_type,
        payload=payload,
        created_at=created_at,
    )
    session.add(event)
    return event

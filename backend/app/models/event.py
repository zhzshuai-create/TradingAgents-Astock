"""job_events table: SSE events carry seq, audit records do not.

sse-events-v1.md section 3 keeps six event types but only five are persisted;
snapshot is built on connect and never written. created, transition_rejected and
reconcile_note are audit records: they live in this table with seq = NULL so they
never punch gaps into the replayable sequence.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, sql_in

SSE_EVENT_TYPES = ("stage_changed", "stats", "status_changed", "report_ready", "error")
AUDIT_EVENT_TYPES = ("created", "transition_rejected", "reconcile_note")
EVENT_TYPES = SSE_EVENT_TYPES + AUDIT_EVENT_TYPES


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int | None] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "seq", name="uq_job_events_job_id_seq"),
        CheckConstraint(sql_in("type", EVENT_TYPES), name="ck_job_events_type"),
        CheckConstraint("seq IS NULL OR seq >= 1", name="ck_job_events_seq_positive"),
    )

"""jobs table: one row per analysis request, nine statuses, frozen field names.

Column names follow the frozen JobDetail contract (api-v1.md section 1.1), not
the shorter working names used in the P1 backlog: ticker_code, analysis_date and
finished_at. Any API response is a projection of this row.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, sql_in

JOB_STATUSES = (
    "queued",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
    "interrupted",
)
ACTIVE_STATUSES = ("queued", "running", "pause_requested", "paused", "cancel_requested")
TERMINAL_STATUSES = ("cancelled", "succeeded", "failed", "interrupted")
PENDING_ACTIONS = ("pause", "cancel")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker_code: Mapped[str] = mapped_column(Text, nullable=False)
    ticker_name: Mapped[str | None] = mapped_column(Text)
    analysis_date: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    pending_action: Mapped[str | None] = mapped_column(Text)

    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    graph_version: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_body_hash: Mapped[str] = mapped_column(Text, nullable=False)

    retry_of_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    resume_of_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    resume_from_stage: Mapped[str | None] = mapped_column(Text)

    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[str | None] = mapped_column(Text)

    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)

    report_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(sql_in("status", JOB_STATUSES), name="ck_jobs_status"),
        CheckConstraint(
            "pending_action IS NULL OR " + sql_in("pending_action", PENDING_ACTIONS),
            name="ck_jobs_pending_action",
        ),
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        # Contract-mandated (idempotency-conflicts.md section 4): the 20-way
        # concurrent create is decided by this partial index, not by app code.
        Index(
            "uniq_active_fingerprint",
            "ticker_code",
            "analysis_date",
            "config_hash",
            unique=True,
            sqlite_where=text(sql_in("status", ACTIVE_STATUSES)),
        ),
    )

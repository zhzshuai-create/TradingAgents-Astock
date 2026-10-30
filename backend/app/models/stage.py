"""job_stages table: 12 fixed stage ids per job, five stage statuses."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, sql_in

STAGE_IDS = (
    "market",
    "social",
    "news",
    "fundamentals",
    "policy",
    "hot_money",
    "lockup",
    "quality_gate",
    "debate",
    "trader",
    "risk",
    "pm",
)
STAGE_STATUSES = ("pending", "active", "done", "failed", "skipped")


class JobStage(Base):
    __tablename__ = "job_stages"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    stage_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    ended_at: Mapped[str | None] = mapped_column(Text)
    report_path: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(sql_in("stage_id", STAGE_IDS), name="ck_job_stages_stage_id"),
        CheckConstraint(sql_in("status", STAGE_STATUSES), name="ck_job_stages_status"),
    )

"""report_exports: one PDF export per (report, content, version, template).

The row is a cache record and a state machine, never part of the ReportDTO.
``file_path`` is relative to ``TA_EXPORTS_DIR``; responses only expose
``/api/v1/exports/{id}/file``. The unique key is the frozen cache key, so the
same report and content can never fan out into two renders.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, sql_in

EXPORT_STATUSES = ("queued", "rendering", "ready", "failed")
EXPORT_TEMPLATES = ("default",)


class ReportExport(Base):
    __tablename__ = "report_exports"

    export_id: Mapped[str] = mapped_column(Text, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    exporter_version: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    ready_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            sql_in("status", EXPORT_STATUSES), name="ck_report_exports_status"
        ),
        UniqueConstraint(
            "report_id",
            "content_hash",
            "exporter_version",
            "template",
            name="uq_report_exports_cache",
        ),
        Index("ix_report_exports_report_id", "report_id"),
    )

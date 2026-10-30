"""reports table: one immutable ReportDTO row per successful job.

Column names mirror report-schema-v1 section 2. ``payload`` stores the whole
ReportDTO verbatim so readers never have to re-derive sections; the separate
columns exist for list filters and for the report_ready payload. ``job_id`` is
unique but nullable: manual imports from B4 have no owning job, and SQLite
allows many NULLs in a unique index.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, JSON, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, sql_in

REPORT_ORIGINS = ("new", "legacy_import")
GENERATED_AT_SOURCES = ("job_clock", "import_clock", "unknown")
DATA_QUALITY_STATUSES = ("ok", "degraded", "absent")
CHART_SNAPSHOT_STATUSES = ("frozen", "refetch_needed", "none")
REPORT_RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell", "unknown")
REPORT_SIGNALS = ("Buy", "Hold", "Sell", "unknown")


class Report(Base):
    __tablename__ = "reports"

    report_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    ticker_code: Mapped[str] = mapped_column(Text, nullable=False)
    ticker_name: Mapped[str | None] = mapped_column(Text)
    analysis_date: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[str | None] = mapped_column(Text)
    generated_at_source: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    config_digest: Mapped[str | None] = mapped_column(Text)
    data_quality_status: Mapped[str] = mapped_column(Text, nullable=False)
    chart_snapshot_status: Mapped[str] = mapped_column(Text, nullable=False)
    retry_of_job_id: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[str] = mapped_column(Text, nullable=False)
    signal: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "schema_version = 'report-v1'", name="ck_reports_schema_version"
        ),
        CheckConstraint(sql_in("origin", REPORT_ORIGINS), name="ck_reports_origin"),
        CheckConstraint(
            sql_in("generated_at_source", GENERATED_AT_SOURCES),
            name="ck_reports_generated_at_source",
        ),
        CheckConstraint(
            sql_in("data_quality_status", DATA_QUALITY_STATUSES),
            name="ck_reports_data_quality_status",
        ),
        CheckConstraint(
            sql_in("chart_snapshot_status", CHART_SNAPSHOT_STATUSES),
            name="ck_reports_chart_snapshot_status",
        ),
        CheckConstraint(sql_in("rating", REPORT_RATINGS), name="ck_reports_rating"),
        CheckConstraint(sql_in("signal", REPORT_SIGNALS), name="ck_reports_signal"),
        UniqueConstraint("job_id", name="uq_reports_job_id"),
        Index(
            "ix_reports_ticker_date",
            "ticker_code",
            "analysis_date",
            "generated_at",
        ),
    )

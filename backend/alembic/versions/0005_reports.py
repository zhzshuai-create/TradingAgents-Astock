"""reports

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30

Immutable ReportDTO rows for T03 succeeded (P1-09). ``payload`` keeps the full
report-schema-v1 document; the scalar columns are the list-filter projection
and the report_ready payload. ``uq_reports_job_id`` makes "one report per job"
a database fact, so a duplicate terminal commit cannot create a second report.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("report_id", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column("ticker_code", sa.Text(), nullable=False),
        sa.Column("ticker_name", sa.Text(), nullable=True),
        sa.Column("analysis_date", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.Text(), nullable=True),
        sa.Column("generated_at_source", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("config_digest", sa.Text(), nullable=True),
        sa.Column("data_quality_status", sa.Text(), nullable=False),
        sa.Column("chart_snapshot_status", sa.Text(), nullable=False),
        sa.Column("retry_of_job_id", sa.Text(), nullable=True),
        sa.Column("rating", sa.Text(), nullable=False),
        sa.Column("signal", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'report-v1'", name="ck_reports_schema_version"
        ),
        sa.CheckConstraint(
            "origin IN ('new', 'legacy_import')", name="ck_reports_origin"
        ),
        sa.CheckConstraint(
            "generated_at_source IN ('job_clock', 'import_clock', 'unknown')",
            name="ck_reports_generated_at_source",
        ),
        sa.CheckConstraint(
            "data_quality_status IN ('ok', 'degraded', 'absent')",
            name="ck_reports_data_quality_status",
        ),
        sa.CheckConstraint(
            "chart_snapshot_status IN ('frozen', 'refetch_needed', 'none')",
            name="ck_reports_chart_snapshot_status",
        ),
        sa.CheckConstraint(
            "rating IN ('Buy', 'Overweight', 'Hold', 'Underweight', 'Sell', "
            "'unknown')",
            name="ck_reports_rating",
        ),
        sa.CheckConstraint(
            "signal IN ('Buy', 'Hold', 'Sell', 'unknown')",
            name="ck_reports_signal",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_reports_job_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("job_id", name="uq_reports_job_id"),
    )
    op.create_index(
        "ix_reports_ticker_date",
        "reports",
        ["ticker_code", "analysis_date", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reports_ticker_date", table_name="reports")
    op.drop_table("reports")

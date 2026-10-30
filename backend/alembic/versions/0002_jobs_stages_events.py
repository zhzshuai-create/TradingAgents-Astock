"""jobs, job_stages and job_events

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30

Field names and enum values are copied as literals from the frozen contracts.
Migrations must stay readable without importing application models, so the
tuples below are intentionally duplicated instead of imported.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

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
EVENT_TYPES = (
    "stage_changed",
    "stats",
    "status_changed",
    "report_ready",
    "error",
    "created",
    "transition_rejected",
    "reconcile_note",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join("'" + value + "'" for value in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("ticker_code", sa.Text(), nullable=False),
        sa.Column("ticker_name", sa.Text(), nullable=True),
        sa.Column("analysis_date", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pending_action", sa.Text(), nullable=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("graph_version", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("idempotency_body_hash", sa.Text(), nullable=False),
        sa.Column("retry_of_job_id", sa.Text(), nullable=True),
        sa.Column("resume_of_job_id", sa.Text(), nullable=True),
        sa.Column("resume_from_stage", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("report_id", sa.Text(), nullable=True),
        sa.CheckConstraint(_in("status", JOB_STATUSES), name="ck_jobs_status"),
        sa.CheckConstraint(
            "pending_action IS NULL OR " + _in("pending_action", ("pause", "cancel")),
            name="ck_jobs_pending_action",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["retry_of_job_id"], ["jobs.id"], name="fk_jobs_retry_of_job_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resume_of_job_id"], ["jobs.id"], name="fk_jobs_resume_of_job_id", ondelete="SET NULL"
        ),
    )
    op.create_index(
        "uniq_active_fingerprint",
        "jobs",
        ["ticker_code", "analysis_date", "config_hash"],
        unique=True,
        sqlite_where=sa.text(_in("status", ACTIVE_STATUSES)),
    )

    op.create_table(
        "job_stages",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("stage_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("ended_at", sa.Text(), nullable=True),
        sa.Column("report_path", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("job_id", "stage_id", name="pk_job_stages"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_job_stages_job_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint(_in("stage_id", STAGE_IDS), name="ck_job_stages_stage_id"),
        sa.CheckConstraint(_in("status", STAGE_STATUSES), name="ck_job_stages_status"),
    )

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_job_events_job_id", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("job_id", "seq", name="uq_job_events_job_id_seq"),
        sa.CheckConstraint(_in("type", EVENT_TYPES), name="ck_job_events_type"),
        sa.CheckConstraint("seq IS NULL OR seq >= 1", name="ck_job_events_seq_positive"),
    )


def downgrade() -> None:
    op.drop_table("job_events")
    op.drop_table("job_stages")
    op.drop_table("jobs")

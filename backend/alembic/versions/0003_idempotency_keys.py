"""job_idempotency_keys

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-30

The jobs table keeps the creating key for diagnostics. This table records every
key that resolved to a job, including keys that hit idempotency-conflicts.md
step 3 against an already-active job.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_idempotency_keys",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_idempotency_keys_job_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_job_idempotency_keys_job_id",
        "job_idempotency_keys",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_idempotency_keys_job_id", table_name="job_idempotency_keys")
    op.drop_table("job_idempotency_keys")

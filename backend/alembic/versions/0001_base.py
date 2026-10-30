"""base

Revision ID: 0001
Revises:
Create Date: 2026-10-30

Creates the kernel metadata table. Domain tables (jobs, stages, events) arrive
in 0002; this revision only proves the upgrade/downgrade rail works on an empty
database and gives later migrations a stable contract marker to read.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_CONTRACT = "p0-contracts-v1"


def upgrade() -> None:
    op.create_table(
        "job_kernel_meta",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.Text(),
            nullable=False,
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ','now'))"),
        ),
    )
    op.execute(
        "INSERT INTO job_kernel_meta (key, value) "
        f"VALUES ('schema_contract', '{SCHEMA_CONTRACT}')"
    )


def downgrade() -> None:
    op.drop_table("job_kernel_meta")

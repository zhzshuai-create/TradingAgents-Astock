"""worker_lease

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30

Single-row lease for the one worker process, seeded free (owner NULL). The
CHECK constraint keeps it single-row; lease takeover relies on compare-and-swap
against owner/expires_at, never on deleting or re-inserting the row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_lease",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_worker_lease_single_row"),
    )
    op.execute(
        "INSERT INTO worker_lease (id, owner, expires_at, updated_at) "
        "VALUES (1, NULL, NULL, NULL)"
    )


def downgrade() -> None:
    op.drop_table("worker_lease")

"""legacy_imports

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-06

Idempotency ledger for imported ``full_states_log_*.json`` files (P3-02).
``(source_path, content_hash)`` is the key: re-scanning an unchanged file adds
nothing, re-scanning a changed file adds a new report and a new ledger row, and
a concurrent import loses the insert race on the primary key instead of
duplicating a report. The path never enters the ReportDTO (report-schema-v1 is
``additionalProperties: false``), so this table is the only place it exists.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_imports",
        sa.Column("source_path", sa.Text(), primary_key=True),
        sa.Column("content_hash", sa.Text(), primary_key=True),
        sa.Column("report_id", sa.Text(), nullable=False),
        sa.Column("imported_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_id"],
            name="fk_legacy_imports_report_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_legacy_imports_report_id", "legacy_imports", ["report_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_legacy_imports_report_id", table_name="legacy_imports")
    op.drop_table("legacy_imports")

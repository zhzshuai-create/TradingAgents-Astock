"""report_exports

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06

PDF export cache and state machine (P3-03). ``(report_id, content_hash,
exporter_version, template)`` is the frozen cache key; ``file_path`` is
relative to ``TA_EXPORTS_DIR`` and never leaves the server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_exports",
        sa.Column("export_id", sa.Text(), primary_key=True),
        sa.Column("report_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("exporter_version", sa.Text(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("ready_at", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'rendering', 'ready', 'failed')",
            name="ck_report_exports_status",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.report_id"],
            name="fk_report_exports_report_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_report_exports_cache",
        "report_exports",
        ["report_id", "content_hash", "exporter_version", "template"],
        unique=True,
    )
    op.create_index(
        "ix_report_exports_report_id", "report_exports", ["report_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_report_exports_report_id", table_name="report_exports")
    op.drop_index("uq_report_exports_cache", table_name="report_exports")
    op.drop_table("report_exports")

"""legacy_imports: which source file produced which report, and at what content.

The composite primary key makes the import idempotent at the database level;
``content_hash`` is the report's sections hash, so "same content" always means
"the same rendered report". ``source_path`` is absolute and never appears in
the ReportDTO.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class LegacyImport(Base):
    __tablename__ = "legacy_imports"

    source_path: Mapped[str] = mapped_column(Text, primary_key=True)
    content_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False
    )
    imported_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_legacy_imports_report_id", "report_id"),)

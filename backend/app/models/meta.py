"""job_kernel_meta table, created by revision 0001.

Kept in the ORM metadata so autogenerate never proposes dropping the base
table. It is infrastructure, not a domain table.
"""

from __future__ import annotations

from sqlalchemy import Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class JobKernelMeta(Base):
    __tablename__ = "job_kernel_meta"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%fZ','now'))"),
    )

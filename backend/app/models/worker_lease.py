"""worker_lease: the single row that allows exactly one worker process.

The row is seeded by migration 0004. owner NULL means the lease is free; an
expired row can be taken over by the next worker without human action, because
a dead worker must not block the queue forever.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base

LEASE_ROW_ID = 1


class WorkerLease(Base):
    __tablename__ = "worker_lease"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    owner: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_worker_lease_single_row"),
    )

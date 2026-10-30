"""job_idempotency_keys: every key that ever pointed at a job.

A job row stores only the key that created it, but the contract's step 3 lets a
first-seen key resolve to an already-active job. Recording that binding here is
what makes a later replay of the same key return step 1/2 instead of falling
through to step 4 with the wrong error code.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class JobIdempotencyKey(Base):
    __tablename__ = "job_idempotency_keys"

    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

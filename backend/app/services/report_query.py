"""Read-only report queries for api-v1.md section 2 (P3-01).

List order is ``generated_at DESC, report_id ASC`` with null ``generated_at``
last (report-schema-v1 section 4.2). The keyset cursor carries the null bucket
explicitly: encoding only the timestamp would make null rows repeat or vanish
at a page boundary.

Nothing here writes: no reconciliation, no export rows, no filesystem access.
``summary_available`` is true because P3 stores the whole DTO in ``payload``;
the flag lets the list avoid promising a summary that a future projection might
not have.
"""

from __future__ import annotations

import base64
import binascii
import copy
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.models.report import Report

LIST_DEFAULT_LIMIT = 20
LIST_MAX_LIMIT = 100
CURSOR_SEPARATOR = "\x1f"
NULL_BUCKET = "1"
VALUE_BUCKET = "0"


class InvalidCursor(Exception):
    """An opaque report-list cursor that cannot be decoded (400 invalid_request)."""


@dataclass(frozen=True)
class ReportListPage:
    items: list[Report]
    next_cursor: str | None


def report_summary(report: Report) -> dict[str, Any]:
    """ReportDTO without ``sections`` (api-v1.md 2.1)."""
    return {
        "meta": copy.deepcopy(report.payload["meta"]),
        "summary_available": True,
    }


class ReportQuery:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_reports(
        self,
        *,
        ticker: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        ratings: Sequence[str] = (),
        limit: int = LIST_DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> ReportListPage:
        """Keyset paginated pure read; ``from > to`` is an empty page."""
        if date_from and date_to and date_from > date_to:
            return ReportListPage(items=[], next_cursor=None)

        conditions: list[Any] = []
        if ticker:
            conditions.append(Report.ticker_code == ticker)
        if date_from:
            conditions.append(Report.analysis_date >= date_from)
        if date_to:
            conditions.append(Report.analysis_date <= date_to)
        if ratings:
            conditions.append(Report.rating.in_(list(ratings)))

        limit = max(1, min(limit, LIST_MAX_LIMIT))
        after = decode_cursor(cursor) if cursor else None
        if after is not None:
            generated_at, report_id, has_time = after
            if has_time:
                conditions.append(
                    or_(
                        Report.generated_at.is_(None),
                        Report.generated_at < generated_at,
                        and_(
                            Report.generated_at == generated_at,
                            Report.report_id > report_id,
                        ),
                    )
                )
            else:
                conditions.append(
                    and_(
                        Report.generated_at.is_(None),
                        Report.report_id > report_id,
                    )
                )

        with Session(self._engine) as session:
            ordered = list(
                session.execute(
                    select(Report.report_id, Report.generated_at)
                    .where(*conditions)
                    .order_by(
                        Report.generated_at.is_(None).asc(),
                        Report.generated_at.desc(),
                        Report.report_id.asc(),
                    )
                    .limit(limit + 1)
                )
            )
            has_more = len(ordered) > limit
            ordered = ordered[:limit]
            if not ordered:
                return ReportListPage(items=[], next_cursor=None)
            page_ids = [report_id for report_id, _ in ordered]
            # Two-phase read: ordering touches only small columns, so the
            # temporary sort never has to carry the JSON payload of 10k rows.
            fetched = session.scalars(
                select(Report).where(Report.report_id.in_(page_ids))
            )
            by_id = {report.report_id: report for report in fetched}
            items = [by_id[report_id] for report_id in page_ids]

        next_cursor = None
        if has_more:
            last_report_id, last_generated_at = ordered[-1]
            next_cursor = encode_cursor(
                generated_at=last_generated_at, report_id=last_report_id
            )
        return ReportListPage(items=items, next_cursor=next_cursor)

    def get_report(self, report_id: str) -> Report | None:
        with Session(self._engine) as session:
            return session.get(Report, report_id)


def encode_cursor(*, generated_at: str | None, report_id: str) -> str:
    bucket = NULL_BUCKET if generated_at is None else VALUE_BUCKET
    raw = f"{bucket}{CURSOR_SEPARATOR}{generated_at or ''}{CURSOR_SEPARATOR}{report_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str | None, str, bool]:
    """Return ``(generated_at, report_id, has_time)``; raise InvalidCursor."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        ).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidCursor() from exc

    bucket, separator, rest = raw.partition(CURSOR_SEPARATOR)
    if not separator:
        raise InvalidCursor()
    generated_at, separator, report_id = rest.partition(CURSOR_SEPARATOR)
    if not separator or not report_id:
        raise InvalidCursor()

    if bucket == NULL_BUCKET:
        if generated_at:
            raise InvalidCursor()
        return None, report_id, False
    if bucket != VALUE_BUCKET or not generated_at:
        raise InvalidCursor()
    try:
        datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise InvalidCursor() from exc
    return generated_at, report_id, True

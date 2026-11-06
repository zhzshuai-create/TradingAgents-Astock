"""Beijing time, trading-day and market-session helpers for market data.

No holiday calendar is kept here on purpose (P4-01 boundary): on a holiday the
session simply follows the weekday rule and any data whose date precedes the
latest weekday is reported as ``trading_day_mismatch`` instead of being
pretended fresh.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

CST = timezone(timedelta(hours=8))

MORNING_OPEN = time(9, 30)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)

SESSIONS = ("pre_open", "trading", "lunch_break", "closed")


def now_cst() -> datetime:
    return datetime.now(CST)


def to_cst(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=CST)
    return value.astimezone(CST)


def format_cst(value: datetime) -> str:
    """ISO8601 with the ``+08:00`` offset, second precision."""
    return to_cst(value).isoformat(timespec="seconds")


def parse_day(value: str | date | None) -> date | None:
    if isinstance(value, datetime):
        return to_cst(value).date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5


def previous_trading_day(day: date) -> date:
    cursor = day
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def latest_trading_day(now: datetime | None = None) -> date:
    """Most recent day whose session has started (today counts from 09:30)."""
    current = to_cst(now or now_cst())
    day = current.date()
    if is_trading_day(day) and current.time() >= MORNING_OPEN:
        return day
    return previous_trading_day(day - timedelta(days=1))


def market_session(now: datetime | None = None) -> str:
    current = to_cst(now or now_cst())
    if not is_trading_day(current.date()):
        return "closed"
    clock = current.time()
    if clock < MORNING_OPEN:
        return "pre_open"
    if clock < MORNING_CLOSE:
        return "trading"
    if clock < AFTERNOON_OPEN:
        return "lunch_break"
    if clock < AFTERNOON_CLOSE:
        return "trading"
    return "closed"


def trading_day_mismatch(as_of: str | date | None, now: datetime | None = None) -> bool:
    """True when ``as_of`` predates the latest trading day."""
    day = parse_day(as_of)
    if day is None:
        return False
    return day < latest_trading_day(now)

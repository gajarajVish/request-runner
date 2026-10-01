"""The one source of "now" for all workflow and scheduling code.

In development the demo clock adds a persisted offset to real time, so overdue items and
escalations can be shown live. Advancing is idempotent per key and disabled in production.
All datetimes are naive UTC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .config import get_settings
from .models import ClockState

_fixed: datetime | None = None  # tests pin time here


def real_utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def set_fixed(dt: datetime | None) -> None:
    global _fixed
    _fixed = dt


def _offset(session: Session) -> int:
    row = session.get(ClockState, 1)
    return row.offset_seconds if row else 0


def now(session: Session) -> datetime:
    if _fixed is not None:
        return _fixed
    if not get_settings().is_dev:
        return real_utcnow()
    return real_utcnow() + timedelta(seconds=_offset(session))


def advance(session: Session, seconds: int, key: str) -> bool:
    """Shift the demo clock. Returns False if this key was already applied."""
    global _fixed
    if not get_settings().is_dev:
        raise PermissionError("demo clock is disabled outside development")
    row = session.get(ClockState, 1)
    if row is None:
        row = ClockState(id=1, offset_seconds=0)
        session.add(row)
    if row.last_advance_key == key:
        return False
    row.offset_seconds += int(seconds)
    row.last_advance_key = key
    if _fixed is not None:
        _fixed = _fixed + timedelta(seconds=seconds)
    return True


def local_date(dt: datetime, tz: str) -> date:
    return dt.replace(tzinfo=UTC).astimezone(ZoneInfo(tz)).date()


def start_of_local_day(d: date, tz: str) -> datetime:
    local = datetime(d.year, d.month, d.day, 9, 0, tzinfo=ZoneInfo(tz))  # 9am local
    return local.astimezone(UTC).replace(tzinfo=None)


def add_business_days(d: date, n: int) -> date:
    cur = d
    while n > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n -= 1
    return cur

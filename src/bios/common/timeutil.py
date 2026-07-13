"""Time discipline (MASTER_SYSTEM_DESIGN §7, §18).

Everything in BIOS is timezone-aware UTC. Naive datetimes are rejected at
the boundary — the ``occurred_at`` / ``known_at`` separation that prevents
look-ahead bias is meaningless if clock values are ambiguous.
"""

from datetime import UTC, datetime
from enum import StrEnum

from bios.common.errors import BiosError


class TimePrecision(StrEnum):
    """How precisely an event's time is known (coarse for historical events)."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


def utc_now() -> datetime:
    """Current time, tz-aware UTC."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC; reject naive datetimes."""
    if value.tzinfo is None:
        raise BiosError(f"naive datetime rejected: {value!r} (all BIOS times are tz-aware UTC)")
    return value.astimezone(UTC)


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 string into tz-aware UTC; reject naive strings."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BiosError(f"unparsable ISO-8601 datetime: {value!r}") from exc
    return ensure_utc(parsed)

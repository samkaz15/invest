"""Time discipline tests: naive datetimes must never get in."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from bios.common import BiosError, ensure_utc, parse_utc, utc_now


def test_utc_now_is_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_ensure_utc_converts_offsets() -> None:
    jst = timezone(timedelta(hours=9))
    value = datetime(2026, 7, 14, 6, 0, tzinfo=jst)
    assert ensure_utc(value) == datetime(2026, 7, 13, 21, 0, tzinfo=UTC)


def test_ensure_utc_rejects_naive() -> None:
    with pytest.raises(BiosError, match="naive"):
        ensure_utc(datetime(2026, 7, 14, 6, 0))


def test_parse_utc_roundtrip_and_rejections() -> None:
    assert parse_utc("2024-01-10T21:00:00+00:00") == datetime(2024, 1, 10, 21, 0, tzinfo=UTC)
    with pytest.raises(BiosError, match="naive"):
        parse_utc("2024-01-10T21:00:00")
    with pytest.raises(BiosError, match="unparsable"):
        parse_utc("not-a-date")

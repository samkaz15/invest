"""The publication schedule, and the two ways it goes quietly wrong.

A calendar fails silently in a way most code does not. If the time is off by
an hour, nothing raises — the report simply says this morning's CPI is out
tomorrow, and it is right again six months later when the clocks change
back. If the provider answers with an error body, an empty list reads as "a
quiet week" forever. Both are covered here.
"""

from datetime import date

import pytest

from mios.common.errors import MiosError
from mios.config.calendar import WatchedRelease
from mios.series.calendar import (
    DATE_ONLY,
    EXACT,
    CalendarParseError,
    ScheduledRelease,
    fred_release_dates,
    scheduled_at,
)

PAYLOAD = """
{"realtime_start": "2026-09-14", "release_dates": [
  {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-09-15"},
  {"release_id": 50, "release_name": "Employment Situation", "date": "2026-10-02"}
]}
"""


def _watched(local: str = "08:30", tz: str = "America/New_York") -> WatchedRelease:
    return WatchedRelease.model_validate(
        {
            "release_name": "Consumer Price Index",
            "country": "US",
            "importance": 5,
            "local_time": local,
            "timezone": tz,
            "event_type": "release.us_inflation.cpi",
            "series": ["ser_us_cpi_index"],
        }
    )


def _release(day: str, name: str = "Consumer Price Index") -> ScheduledRelease:
    return ScheduledRelease(
        provider_release_id="10", release_name=name, release_date=date.fromisoformat(day)
    )


# --------------------------------------------------------------------- parse


def test_it_reads_the_scheduled_releases() -> None:
    releases = fred_release_dates(PAYLOAD)
    assert [(r.release_name, r.release_date.isoformat()) for r in releases] == [
        ("Consumer Price Index", "2026-09-15"),
        ("Employment Situation", "2026-10-02"),
    ]


def test_a_provider_error_body_is_not_an_empty_schedule() -> None:
    """FRED answers a bad key with HTTP 200 and an error_message.

    Returning an empty list there would read upstream as "nothing is
    scheduled", which looks exactly like a quiet week and would persist
    until somebody noticed the calendar had been blank for a month.
    """
    body = '{"error_code": 400, "error_message": "Bad Request. The value for variable api_key"}'
    with pytest.raises(CalendarParseError, match="provider error"):
        fred_release_dates(body)


def test_a_missing_release_dates_key_lists_the_keys_that_were_there() -> None:
    with pytest.raises(CalendarParseError, match="keys present"):
        fred_release_dates('{"releases": []}')


def test_a_response_with_rows_but_no_usable_ones_fails() -> None:
    with pytest.raises(CalendarParseError, match="none carried a usable"):
        fred_release_dates('{"release_dates": [{"date": "2026-09-15"}]}')


def test_an_html_error_page_is_not_a_schedule() -> None:
    with pytest.raises(CalendarParseError):
        fred_release_dates("<html>503</html>")


# ----------------------------------------------------------------- the clock


def test_summer_and_winter_both_come_out_right() -> None:
    """The reason the timezone is a name and never a fixed offset.

    08:30 in New York is 12:30 UTC in September and 13:30 UTC in January. A
    hard-coded offset is wrong for roughly half the year, and wrong in the
    way that puts a release on the wrong side of midnight — which is how a
    report ends up announcing this morning's CPI as tomorrow's.
    """
    summer, precision = scheduled_at(_release("2026-09-15"), _watched())
    assert precision == EXACT
    assert summer.isoformat() == "2026-09-15T12:30:00+00:00"

    winter, _ = scheduled_at(_release("2026-01-13"), _watched())
    assert winter.isoformat() == "2026-01-13T13:30:00+00:00"


def test_jolts_keeps_its_own_hour() -> None:
    """JOLTS is 10:00 ET while the other labour releases are 08:30.

    Worth its own test because the wrong one is plausible: a single default
    applied to every labour statistic would be right four times out of five.
    """
    when, _ = scheduled_at(_release("2026-09-09"), _watched(local="10:00"))
    assert when.isoformat() == "2026-09-09T14:00:00+00:00"


def test_an_unconfigured_release_keeps_its_time_unknown() -> None:
    """The provider gave a date. Midnight UTC is a claim nobody made.

    Storing it without the flag would sort a Beige Book ahead of the
    previous evening's close and read as a precise 00:00 publication.
    """
    when, precision = scheduled_at(_release("2026-09-16", "Beige Book"), None)
    assert precision == DATE_ONLY
    assert when.isoformat() == "2026-09-16T00:00:00+00:00"


def test_an_unknown_timezone_is_refused_at_config_load() -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        _watched(tz="America/Nowhere")


def test_parse_errors_are_mios_errors() -> None:
    """So the daily chain reports them as a failed step rather than crashing."""
    assert issubclass(CalendarParseError, MiosError)

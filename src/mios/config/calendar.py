"""Typed schema for ``config/calendar.yaml`` — when each release is published.

FRED's release-dates endpoint returns a date and nothing else. The BLS
publishes CPI at 08:30 America/New_York; FRED will tell you it is the 15th.
Those are different states of knowledge, and the whole point of this file is
to record the publication times that are genuinely known so the rest can
stay honestly date-only rather than quietly becoming midnight UTC.

Times are held as a local time plus a timezone name, never as a fixed
offset. 08:30 in New York is 12:30 UTC in summer and 13:30 UTC in winter,
and a hard-coded offset is wrong for roughly half the year — which is the
kind of error that shows up as a report listing this morning's release as
tomorrow's.
"""

from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from mios.common.ids import IdKind, pydantic_id_validator
from mios.common.labels import Country
from mios.common.schema import MiosModel

#: The type given to a release the provider lists and this file does not
#: describe. Naming it is better than guessing its category, and it lives
#: here rather than in the ingestor because the taxonomy check that
#: exempts it runs at config load.
UNCATEGORISED = "release.other.uncategorised"


class WatchedRelease(MiosModel):
    """One publication MIOS follows closely enough to know its clock."""

    #: Must match the release name in the provider's payload exactly. Matched
    #: by name rather than by numeric id because a name can be checked by
    #: eye, and a mismatch can fail with the real names listed.
    release_name: str = Field(min_length=3)
    country: Country
    importance: int = Field(ge=1, le=5)
    local_time: time
    timezone: str
    event_type: str
    #: The series this release publishes. May be empty for a release MIOS
    #: wants on the calendar without tracking its numbers.
    series: list[str] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {v!r}: {exc}") from exc
        return v

    @field_validator("series")
    @classmethod
    def _series(cls, v: list[str]) -> list[str]:
        return [pydantic_id_validator(s, IdKind.SERIES) for s in v]

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class CalendarConfig(MiosModel):
    watch: list[WatchedRelease] = Field(default_factory=list)

    def by_name(self) -> dict[str, WatchedRelease]:
        return {w.release_name: w for w in self.watch}

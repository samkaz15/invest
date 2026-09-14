"""The publication schedule: what comes out, and when.

This is the piece the rest of the system was built on top of without ever
having. `economic_calendar` has existed since migration 0005 and nothing
wrote to it, so "what is released today?" had no answer — which is the
first question anyone actually asks in the morning.

Two rules shape it, and both are about not inventing the thing being asked
for.

**An unknown time stays unknown.** The provider returns a date. Storing that
as a timestamptz makes every date-only entry midnight UTC, which is a claim
nobody made and which sorts a CPI print ahead of the previous evening. Only
releases whose publication clock is stated in config/calendar.yaml are
recorded as exact; the rest carry `time_precision = 'date_only'` and are
displayed as a day.

**The schedule is the one thing here that may change.** Every other table in
MIOS refuses updates, because a measured value that can be edited is not
evidence. A schedule is the opposite: it is a claim about the future, and
publishers move dates. So this writes with an upsert, deliberately, and it
is the only module in the project that does.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from mios.common.errors import MiosError
from mios.common.ids import IdKind, make_dated_id, slugify
from mios.common.logutil import get_logger
from mios.config.calendar import UNCATEGORISED, CalendarConfig, WatchedRelease
from mios.ingestion.rawstore import RawStore
from mios.storage.db import Database

logger = get_logger(__name__)

#: A release nobody configured a time for. Listing it is still worth doing —
#: the reader learns something is out today — but the hour is not invented.
DATE_ONLY = "date_only"
EXACT = "exact"


class CalendarParseError(MiosError):
    """The schedule payload did not contain what was expected."""


@dataclass(frozen=True)
class ScheduledRelease:
    """One dated publication, as the provider reported it."""

    provider_release_id: str
    release_name: str
    release_date: date


def fred_release_dates(payload: str) -> list[ScheduledRelease]:
    """Read FRED's ``releases/dates`` response.

    The failure mode worth guarding is not a crash. FRED answers an invalid
    key with HTTP 200 and an ``error_message`` body; a reader that returned
    an empty list there would be read upstream as "nothing is scheduled",
    which is indistinguishable from a quiet week and would persist forever.
    """
    try:
        data: dict[str, Any] = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CalendarParseError(f"release dates: payload is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CalendarParseError("release dates: payload is not a JSON object")
    if "error_message" in data:
        raise CalendarParseError(f"release dates: provider error: {data['error_message']}")

    rows = data.get("release_dates")
    if not isinstance(rows, list):
        raise CalendarParseError(
            f"release dates: no 'release_dates' list; keys present: {sorted(data)}"
        )

    out: list[ScheduledRelease] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        name = row.get("release_name")
        release_id = row.get("release_id")
        if not raw_date or not name or release_id is None:
            continue
        try:
            parsed = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        out.append(
            ScheduledRelease(
                provider_release_id=str(release_id),
                release_name=str(name),
                release_date=parsed,
            )
        )

    if not out:
        raise CalendarParseError(
            f"release dates: {len(rows)} row(s) returned but none carried a usable "
            "date, release_id and release_name"
        )
    return out


def scheduled_at(release: ScheduledRelease, watched: WatchedRelease | None) -> tuple[datetime, str]:
    """The instant to store, and how well it is known.

    A configured release gets its real publication clock, converted through
    a timezone name so summer and winter both come out right. Everything
    else is stored at the start of its day in UTC and *flagged* as date-only,
    so nothing downstream can mistake the placeholder hour for a time the
    publisher announced.
    """
    if watched is None:
        return datetime.combine(release.release_date, datetime.min.time(), tzinfo=UTC), DATE_ONLY
    local = datetime.combine(release.release_date, watched.local_time, tzinfo=watched.zone)
    return local.astimezone(UTC), EXACT


class CalendarRepo:
    """Reads and writes ``economic_calendar``. The only module that may.

    Every write is an upsert, which is unique in this project and is the
    point: a schedule that could not be corrected would be worse than no
    schedule, because a moved release would stay wrong forever.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, row: dict[str, Any]) -> bool:
        """Store or correct one scheduled release. True when it changed."""
        result = self._db.query_one(
            """
            INSERT INTO economic_calendar (calendar_id, series_id, event_type, country,
                title, scheduled_at, importance, status, source_id, source_url,
                time_precision, provider_release_id)
            VALUES (%(calendar_id)s, %(series_id)s, %(event_type)s, %(country)s,
                %(title)s, %(scheduled_at)s, %(importance)s, 'scheduled', %(source_id)s,
                %(source_url)s, %(time_precision)s, %(provider_release_id)s)
            ON CONFLICT (source_id, provider_release_id, scheduled_at, COALESCE(series_id, ''))
            DO UPDATE SET title = EXCLUDED.title,
                          importance = EXCLUDED.importance,
                          event_type = EXCLUDED.event_type,
                          time_precision = EXCLUDED.time_precision,
                          updated_at = now()
            RETURNING (xmax = 0) AS inserted
            """,
            row,
        )
        return bool(result and result["inserted"])

    def between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Everything scheduled in a window, most important first within a day."""
        return self._db.query(
            """
            SELECT * FROM economic_calendar
            WHERE scheduled_at >= %(s)s AND scheduled_at < %(e)s
            ORDER BY scheduled_at, importance DESC, title
            """,
            {"s": start, "e": end},
        )

    def upcoming(self, after: datetime, limit: int = 20) -> list[dict[str, Any]]:
        return self._db.query(
            """
            SELECT * FROM economic_calendar
            WHERE scheduled_at >= %(a)s
            ORDER BY scheduled_at, importance DESC
            LIMIT %(l)s
            """,
            {"a": after, "l": limit},
        )

    def coverage(self) -> dict[str, int]:
        row = self._db.query_one(
            """
            SELECT count(*) AS entries,
                   count(*) FILTER (WHERE time_precision = 'exact') AS exact,
                   count(DISTINCT provider_release_id) AS releases
            FROM economic_calendar
            """
        )
        return {k: int(v) for k, v in (row or {}).items()}


@dataclass
class CalendarReport:
    raw_items: int = 0
    scheduled: int = 0
    matched: int = 0  # entries tied to a series MIOS tracks
    unmatched: int = 0  # real releases MIOS has no configuration for
    failures: list[str] = field(default_factory=list)
    #: Release names the payload carried, so a mismatched config can be
    #: fixed from one run rather than by reading the provider's website.
    seen_names: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.failures


class CalendarIngestor:
    def __init__(
        self,
        store: RawStore,
        repo: CalendarRepo,
        config: CalendarConfig,
        source_id: str,
        source_url: str,
    ) -> None:
        self._store = store
        self._repo = repo
        self._config = config
        self._source_id = source_id
        self._source_url = source_url

    def run(self) -> CalendarReport:
        report = CalendarReport()
        watched = self._config.by_name()
        latest = self._store.latest(self._source_id)
        if latest is None:
            report.failures.append(
                f"{self._source_id}: no payload collected yet — run `mios collect` first"
            )
            return report

        report.raw_items = 1
        try:
            releases = fred_release_dates(latest.payload_text)
        except CalendarParseError as exc:
            report.failures.append(str(exc))
            logger.error("calendar parse failed: %s", exc)
            return report

        for release in releases:
            report.seen_names.add(release.release_name)
            spec = watched.get(release.release_name)
            when, precision = scheduled_at(release, spec)
            if spec is None:
                # Still worth a row: "something is out today" is information
                # even when MIOS tracks none of its numbers.
                self._write(release, spec, when, precision, series_id=None)
                report.unmatched += 1
                report.scheduled += 1
                continue
            # One row per series, so "which of my series prints today" is a
            # lookup rather than a join through a name.
            for series_id in spec.series or [None]:  # type: ignore[list-item]
                self._write(release, spec, when, precision, series_id=series_id)
                report.scheduled += 1
            report.matched += 1

        logger.info(
            "calendar: scheduled=%d matched=%d unmatched=%d",
            report.scheduled,
            report.matched,
            report.unmatched,
        )
        return report

    def _write(
        self,
        release: ScheduledRelease,
        spec: WatchedRelease | None,
        when: datetime,
        precision: str,
        series_id: str | None,
    ) -> None:
        slug = slugify(f"{release.provider_release_id}-{series_id or 'all'}")
        self._repo.upsert(
            {
                "calendar_id": make_dated_id(IdKind.EVENT, release.release_date.isoformat(), slug),
                "series_id": series_id,
                "event_type": spec.event_type if spec else UNCATEGORISED,
                "country": spec.country.value if spec else "US",
                "title": release.release_name,
                "scheduled_at": when,
                "importance": spec.importance if spec else 1,
                "source_id": self._source_id,
                "source_url": self._source_url,
                "time_precision": precision,
                "provider_release_id": release.provider_release_id,
            }
        )

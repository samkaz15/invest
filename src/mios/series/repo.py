"""Persistence for series and their vintage-keyed observations.

Two rules are enforced here rather than left to callers, because both have
already cost this project once (docs/REPOSITORY_AUDIT.md §14):

1. **A new observation row is written only when the value changed.**
   Re-fetching unchanged history would otherwise add a row per fetch, and
   "how many times did this get revised?" would become unanswerable.

2. **Reads take an as-of instant.** There is no method that returns "the
   current value" of a revisable series, because there is no safe way to
   use one inside an analysis dated in the past.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mios.common.logutil import get_logger
from mios.config.series import SeriesSpec
from mios.storage.db import Database

logger = get_logger(__name__)


@dataclass(frozen=True)
class Observation:
    """One value as it stood at one vintage."""

    series_id: str
    observation_date: date
    vintage_at: datetime
    value: Decimal | None
    revision_n: int


@dataclass(frozen=True)
class WriteResult:
    """What one normalization pass actually changed."""

    written: int = 0
    skipped: int = 0  # unchanged values, correctly not rewritten
    revisions: int = 0  # writes that restated a value we already had

    def __add__(self, other: "WriteResult") -> "WriteResult":
        return WriteResult(
            self.written + other.written,
            self.skipped + other.skipped,
            self.revisions + other.revisions,
        )


class SeriesRepo:
    """Mirror of config/series.yaml, which stays the source of truth."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def sync(self, specs: list[SeriesSpec]) -> int:
        with self._db.transaction() as conn:
            for spec in specs:
                conn.execute(
                    """
                    INSERT INTO series (series_id, name, country, category, unit, frequency,
                        source_id, provider_code, parser, revisable, seasonal_adjustment, notes)
                    VALUES (%(series_id)s, %(name)s, %(country)s, %(category)s, %(unit)s,
                        %(frequency)s, %(source_id)s, %(provider_code)s, %(parser)s,
                        %(revisable)s, %(seasonal_adjustment)s, %(notes)s)
                    ON CONFLICT (series_id) DO UPDATE SET
                        name=EXCLUDED.name, country=EXCLUDED.country,
                        category=EXCLUDED.category, unit=EXCLUDED.unit,
                        frequency=EXCLUDED.frequency, source_id=EXCLUDED.source_id,
                        provider_code=EXCLUDED.provider_code, parser=EXCLUDED.parser,
                        revisable=EXCLUDED.revisable,
                        seasonal_adjustment=EXCLUDED.seasonal_adjustment,
                        notes=EXCLUDED.notes, synced_at=now()
                    """,
                    spec.model_dump(mode="json"),
                )
        return len(specs)

    def get(self, series_id: str) -> dict[str, Any] | None:
        return self._db.query_one("SELECT * FROM series WHERE series_id=%(s)s", {"s": series_id})

    def all(self) -> list[dict[str, Any]]:
        return self._db.query("SELECT * FROM series ORDER BY category, series_id")


class ObservationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------------------------------------------------------------- write

    def _latest_values(self, series_id: str) -> dict[date, tuple[Decimal | None, int]]:
        """Newest vintage per reference period: ``{date: (value, revision_n)}``.

        Loaded in one query and compared in memory. A series carries a few
        hundred periods at most, so this trades a trivial amount of memory
        for not issuing one SELECT per point.
        """
        rows = self._db.query(
            """
            SELECT DISTINCT ON (observation_date) observation_date, value, revision_n
            FROM observations WHERE series_id = %(s)s
            ORDER BY observation_date, vintage_at DESC
            """,
            {"s": series_id},
        )
        return {r["observation_date"]: (r["value"], r["revision_n"]) for r in rows}

    def write_vintage(
        self,
        spec: SeriesSpec,
        points: list[tuple[date, Decimal | None]],
        vintage_at: datetime,
        raw_item_id: str,
    ) -> WriteResult:
        """Record ``points`` as seen at ``vintage_at``; skip unchanged values.

        The skip is the point of the method. Without it, a daily poll of a
        series with 400 periods of history would write 400 rows every day
        and drown the genuine revisions it exists to capture.
        """
        known = self._latest_values(spec.series_id)
        to_write: list[dict[str, Any]] = []
        skipped = revisions = 0

        for observation_date, value in points:
            previous = known.get(observation_date)
            if previous is not None:
                previous_value, previous_revision = previous
                if _same_value(previous_value, value):
                    skipped += 1
                    continue
                revision_n = previous_revision + 1
                revisions += 1
            else:
                revision_n = 0
            to_write.append(
                {
                    "series_id": spec.series_id,
                    "observation_date": observation_date,
                    "vintage_at": vintage_at,
                    "value": value,
                    "revision_n": revision_n,
                    "source_id": spec.source_id,
                    "raw_item_id": raw_item_id,
                }
            )

        if to_write:
            with self._db.transaction() as conn:
                for row in to_write:
                    conn.execute(
                        """
                        INSERT INTO observations (series_id, observation_date, vintage_at,
                            value, revision_n, source_id, raw_item_id)
                        VALUES (%(series_id)s, %(observation_date)s, %(vintage_at)s,
                            %(value)s, %(revision_n)s, %(source_id)s, %(raw_item_id)s)
                        ON CONFLICT (series_id, observation_date, vintage_at) DO NOTHING
                        """,
                        row,
                    )
        if revisions:
            logger.info(
                "%s: %d revision(s) recorded at vintage %s",
                spec.series_id,
                revisions,
                vintage_at.isoformat(),
            )
        return WriteResult(written=len(to_write), skipped=skipped, revisions=revisions)

    # ----------------------------------------------------------------- read

    def as_of(
        self,
        series_id: str,
        as_of: datetime,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Observation]:
        """The series as it was knowable at ``as_of``, oldest period first.

        ``as_of`` is required and has no default. That is deliberate: a
        default would be a silent invitation to read the present while
        analysing the past, which is the bug class this whole schema exists
        to prevent (CONSTITUTION.md Art.6).
        """
        sql = """
            SELECT DISTINCT ON (observation_date)
                   series_id, observation_date, vintage_at, value, revision_n
            FROM observations
            WHERE series_id = %(s)s AND vintage_at <= %(as_of)s
        """
        params: dict[str, Any] = {"s": series_id, "as_of": as_of}
        if start is not None:
            sql += " AND observation_date >= %(start)s"
            params["start"] = start
        if end is not None:
            sql += " AND observation_date <= %(end)s"
            params["end"] = end
        sql += " ORDER BY observation_date, vintage_at DESC"
        return [
            Observation(
                series_id=r["series_id"],
                observation_date=r["observation_date"],
                vintage_at=r["vintage_at"],
                value=r["value"],
                revision_n=r["revision_n"],
            )
            for r in self._db.query(sql, params)
        ]

    def latest_as_of(self, series_id: str, as_of: datetime) -> Observation | None:
        """Most recent reference period knowable at ``as_of``."""
        rows = self.as_of(series_id, as_of)
        return rows[-1] if rows else None

    def revisions(self, series_id: str, observation_date: date) -> list[Observation]:
        """Every vintage of one reference period, oldest first.

        This is the answer to "what did we think August CPI was, and when
        did that change?" — and the reason revisions are rows rather than
        overwrites.
        """
        rows = self._db.query(
            """
            SELECT series_id, observation_date, vintage_at, value, revision_n
            FROM observations WHERE series_id = %(s)s AND observation_date = %(d)s
            ORDER BY vintage_at
            """,
            {"s": series_id, "d": observation_date},
        )
        return [
            Observation(
                series_id=r["series_id"],
                observation_date=r["observation_date"],
                vintage_at=r["vintage_at"],
                value=r["value"],
                revision_n=r["revision_n"],
            )
            for r in rows
        ]

    def coverage(self) -> list[dict[str, Any]]:
        """Per-series row counts and freshness — the input to gap reporting."""
        return self._db.query(
            """
            SELECT s.series_id, s.name, s.category, s.frequency,
                   count(o.*) AS vintages,
                   max(o.observation_date) AS latest_period,
                   max(o.vintage_at) AS latest_vintage
            FROM series s LEFT JOIN observations o ON o.series_id = s.series_id
            GROUP BY s.series_id, s.name, s.category, s.frequency
            ORDER BY s.category, s.series_id
            """
        )


def _same_value(left: Decimal | None, right: Decimal | None) -> bool:
    """Compare two readings, treating a published gap as a real value.

    Decimal comparison is numeric, so a provider reformatting 3.20 as 3.2
    does not masquerade as a revision.
    """
    if left is None or right is None:
        return left is None and right is None
    return left == right

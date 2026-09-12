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
from mios.series.planner import Vintage, plan_writes
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


class NormalizeState:
    """Which raw items have already been turned into observations.

    Lives here rather than in the normalizer so that every statement
    touching the vintage tables is in one module, which is what lets
    tests/unit/test_no_lookahead.py assert that nothing else reads them
    without an as-of.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def processed(self) -> set[tuple[str, str]]:
        rows = self._db.query("SELECT raw_item_id, series_id FROM normalize_state")
        return {(r["raw_item_id"], r["series_id"]) for r in rows}

    def mark(self, raw_item_id: str, series_id: str, written: int, skipped: int) -> None:
        self._db.execute(
            """
            INSERT INTO normalize_state (raw_item_id, series_id, written, skipped)
            VALUES (%(r)s, %(s)s, %(w)s, %(k)s)
            ON CONFLICT (raw_item_id) DO UPDATE SET
                series_id=EXCLUDED.series_id, written=EXCLUDED.written,
                skipped=EXCLUDED.skipped, processed_at=now()
            """,
            {"r": raw_item_id, "s": series_id, "w": written, "k": skipped},
        )


class ObservationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---------------------------------------------------------------- write

    def _vintages(self, series_id: str) -> dict[date, list[Vintage]]:
        """Every stored vintage, grouped by reference period.

        Loaded in one query and planned against in memory. A series holds a
        few hundred periods with a handful of vintages each, so this trades
        trivial memory for not issuing a query per point.
        """
        rows = self._db.query(
            """
            SELECT observation_date, vintage_at, value FROM observations
            WHERE series_id = %(s)s ORDER BY observation_date, vintage_at
            """,
            {"s": series_id},
        )
        grouped: dict[date, list[Vintage]] = {}
        for row in rows:
            grouped.setdefault(row["observation_date"], []).append(
                (row["vintage_at"], row["value"])
            )
        return grouped

    def write_points(
        self,
        spec: SeriesSpec,
        points: list[tuple[date, Decimal | None, datetime | None]],
        raw_item_id: str,
        default_vintage: datetime,
    ) -> WriteResult:
        """Record parsed points, writing only what is new information.

        ``default_vintage`` is used for any point whose feed did not report
        when the value became public — the fetch time, which is the earliest
        this system could have known it.

        The skip is the point of the method. Without it, a daily poll of a
        series with 400 periods of history would write 400 rows every day
        and drown the genuine revisions it exists to capture.
        """
        existing = self._vintages(spec.series_id)
        incoming: dict[date, list[Vintage]] = {}
        for observation_date, value, vintage_at in points:
            incoming.setdefault(observation_date, []).append((vintage_at or default_vintage, value))

        rows: list[dict[str, Any]] = []
        seen = revisions = 0
        for observation_date, candidates in incoming.items():
            seen += len(candidates)
            for planned in plan_writes(existing.get(observation_date, []), candidates):
                revisions += 1 if planned.is_revision else 0
                rows.append(
                    {
                        "series_id": spec.series_id,
                        "observation_date": observation_date,
                        "vintage_at": planned.vintage_at,
                        "value": planned.value,
                        "revision_n": planned.revision_n,
                        "source_id": spec.source_id,
                        "raw_item_id": raw_item_id,
                    }
                )

        if rows:
            with self._db.transaction() as conn:
                for row in rows:
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
            logger.info("%s: %d revision(s) recorded", spec.series_id, revisions)
        return WriteResult(written=len(rows), skipped=seen - len(rows), revisions=revisions)

    def write_vintage(
        self,
        spec: SeriesSpec,
        points: list[tuple[date, Decimal | None]],
        vintage_at: datetime,
        raw_item_id: str,
    ) -> WriteResult:
        """:meth:`write_points` for a feed where every point shares a vintage."""
        return self.write_points(
            spec,
            [(day, value, None) for day, value in points],
            raw_item_id,
            default_vintage=vintage_at,
        )

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

"""Turning stored observations into rows about *publications*.

`releases` is the brief's §14 requirement — actual, forecast, previous,
revised_previous, surprise — and it has been an empty table since migration
0005. This fills it.

It lives in the validation layer rather than in `series` for one reason: the
consensus column. A surprise is by definition a comparison between what was
published and what was expected, and the expectation comes from
`external_forecasts`, which the series layer sits below and cannot see.

Three things are worth stating about how the numbers are built.

**The actual is the first print.** Same rule as forecast scoring, for the
same reason: the figure a release published is fixed forever, while the
latest value moves, and a table of "what was released" whose contents change
when a revision lands is not a record of releases.

**previous and revised_previous are two different readings of one period.**
`previous` is the prior period as it stood the instant before this release
landed — what the market was comparing against. `revised_previous` is that
same period as restated *by* this release. When they differ, the agency
revised history, and that difference is frequently the real news; collapsing
them into one column would delete it (指示書 §14, §26).

**The consensus column stays empty, and that is now permanent.** MIOS
collects no institutional forecasts (ADR-015), so `forecast` is written as
NULL and `surprise` — a generated column over it — is NULL with it. The
columns are left in the schema because applied migrations are not edited,
but nothing will fill them, and the export no longer pretends otherwise.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from mios.common.ids import IdKind, make_dated_id, slugify
from mios.common.logutil import get_logger
from mios.config.series import SeriesRegistry
from mios.series.repo import ObservationRepo
from mios.storage.db import Database
from mios.validation.scoring import first_print

logger = get_logger(__name__)


@dataclass
class ReleaseReport:
    written: int = 0
    already_recorded: int = 0
    unresolved: int = 0  # period has not printed yet, or no previous to compare
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _previous_period(period: date) -> date:
    year, month = (period.year - 1, 12) if period.month == 1 else (period.year, period.month - 1)
    return date(year, month, 1)


class ReleaseBuilder:
    def __init__(
        self,
        db: Database,
        observations: ObservationRepo,
        registry: SeriesRegistry,
    ) -> None:
        self._db = db
        self._observations = observations
        self._registry = registry

    def run(self, as_of: datetime, series_ids: list[str]) -> ReleaseReport:
        """Record every period that has printed and is not yet recorded.

        Idempotent: `releases` is append-only and keyed on (series, period),
        so a second run over the same data writes nothing. A release record
        that could be rewritten would be no more trustworthy than one that
        was never kept.
        """
        report = ReleaseReport()
        recorded = {
            (row["series_id"], row["period"])
            for row in self._db.query("SELECT series_id, period FROM releases")
        }
        for series_id in series_ids:
            for period in self._periods(series_id, as_of):
                if (series_id, period) in recorded:
                    report.already_recorded += 1
                    continue
                if self._record(series_id, period, as_of):
                    report.written += 1
                else:
                    report.unresolved += 1

        logger.info(
            "releases: written=%d already=%d unresolved=%d",
            report.written,
            report.already_recorded,
            report.unresolved,
        )
        return report

    def _periods(self, series_id: str, as_of: datetime) -> list[date]:
        rows = self._observations.as_of(series_id, as_of)
        return [row.observation_date for row in rows if row.value is not None]

    def _record(self, series_id: str, period: date, as_of: datetime) -> bool:
        printed = first_print(self._observations, series_id, period, as_of)
        if printed is None:
            return False
        actual, vintage = printed

        prior = _previous_period(period)
        # What the prior period was *before* this print landed, and what it
        # became *with* it. The gap between the two is the revision.
        before = self._value_at(series_id, prior, _just_before(vintage))
        after = self._value_at(series_id, prior, vintage)
        if before is None:
            # Nothing was in force before this vintage, which means MIOS was
            # not holding the series when this figure appeared — it arrived
            # as part of a backfill. Recording it as a release would stamp
            # it with the fetch time and assert that April 2025 CPI was
            # published the day MIOS first downloaded it, which is false.
            #
            # Backfilled history is still kept, and exported as history. It
            # is simply not a *release*, because nobody could have had an
            # expectation about it at the moment it landed here.
            #
            # The rule admits exactly the right rows without a special case:
            # a series pulled from ALFRED carries real publication vintages,
            # so each of its prints does have a prior state and does qualify.
            return False

        source = self._source_of(series_id)
        if source is None:
            return False

        self._db.execute(
            """
            INSERT INTO releases (release_id, series_id, period, release_at, actual,
                forecast, previous, revised_previous, source_id, source_url, vintage_at,
                basis)
            VALUES (%(release_id)s, %(series_id)s, %(period)s, %(release_at)s, %(actual)s,
                %(forecast)s, %(previous)s, %(revised_previous)s, %(source_id)s,
                %(source_url)s, %(vintage_at)s, 'level')
            ON CONFLICT (series_id, period) DO NOTHING
            """,
            {
                "release_id": make_dated_id(
                    IdKind.RELEASE,
                    vintage.date().isoformat(),
                    slugify(f"{series_id.removeprefix('ser_')}-{period.isoformat()}"),
                ),
                "series_id": series_id,
                "period": period,
                "release_at": vintage,
                "actual": Decimal(str(actual)),
                "forecast": None,
                "previous": before,
                "revised_previous": after,
                "source_id": source[0],
                "source_url": source[1],
                "vintage_at": vintage,
            },
        )
        return True

    def _value_at(self, series_id: str, period: date, as_of: datetime) -> Decimal | None:
        rows = self._observations.as_of(series_id, as_of, start=period, end=period)
        usable = [r for r in rows if r.value is not None]
        return usable[-1].value if usable else None

    def _source_of(self, series_id: str) -> tuple[str, str] | None:
        """Where this figure came from, read from the registry.

        Deliberately not a query against `observations`: that table is
        reachable only through the repository, which requires an as-of, and
        the provenance of a series is a configuration fact rather than
        something to rediscover from stored rows.
        """
        spec = self._registry.by_id().get(series_id)
        if spec is None:
            return None
        return spec.source_id, f"mios://series/{series_id}#{spec.provider_code}"


def _just_before(instant: datetime) -> datetime:
    """The moment immediately preceding a vintage.

    Used to read "what stood before this print". Subtracting a microsecond
    rather than using a strict inequality keeps the repository's as-of
    interface — which takes an instant, never an operator — intact.
    """
    return instant - timedelta(microseconds=1)

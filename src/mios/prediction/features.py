"""Turning stored observations into the handful of numbers a bridge uses.

Every function here reads through :class:`ObservationRepo`, which requires
an as-of instant, so a feature can only ever be built from data that was
knowable at the moment being forecast. That is not a convention — it is the
only way to reach the data at all.

Features return ``None`` rather than a number when the history behind them
is too thin. The caller records a data gap; nobody invents a value from
four observations (CONSTITUTION.md Art.4-3).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from statistics import fmean, pstdev

from mios.series.repo import Observation, ObservationRepo

#: Below this many usable observations, a trend or a spread is noise
#: wearing a number's clothes.
MIN_HISTORY = 8


@dataclass(frozen=True)
class Series:
    """One series' usable history, oldest first, as of some instant."""

    series_id: str
    periods: list[date]
    values: list[float]

    def __len__(self) -> int:
        return len(self.values)

    @property
    def latest(self) -> float | None:
        return self.values[-1] if self.values else None

    @property
    def latest_period(self) -> date | None:
        return self.periods[-1] if self.periods else None


def load(repo: ObservationRepo, series_id: str, as_of: datetime) -> Series:
    """A series as it was knowable at ``as_of``, with published gaps dropped.

    Gaps are preserved in storage because "the agency reported no figure"
    is information, but arithmetic cannot use them, so they are removed
    here — and their removal shows up as a shorter history, which the
    minimum-sample checks then act on.
    """
    rows: list[Observation] = repo.as_of(series_id, as_of)
    usable = [(r.observation_date, r.value) for r in rows if r.value is not None]
    return Series(
        series_id=series_id,
        periods=[period for period, _ in usable],
        values=[float(value) for _, value in usable if value is not None],
    )


def pct_change(series: Series, periods: int = 1) -> float | None:
    """Percent change over ``periods`` steps, as a fraction (0.003 = 0.3%)."""
    if len(series) <= periods:
        return None
    previous = series.values[-1 - periods]
    if previous == 0:
        return None
    return series.values[-1] / previous - 1


def mom_series(series: Series) -> list[float]:
    """Period-over-period percent changes, oldest first."""
    return [
        series.values[i] / series.values[i - 1] - 1
        for i in range(1, len(series))
        if series.values[i - 1] != 0
    ]


def diff_series(series: Series) -> list[float]:
    """Period-over-period differences in level (for counts like payrolls)."""
    return [series.values[i] - series.values[i - 1] for i in range(1, len(series))]


def trailing_mean(values: list[float], window: int, min_n: int = 3) -> float | None:
    if len(values) < min_n:
        return None
    return fmean(values[-window:])


def deviation_from_trend(
    values: list[float], window: int = 12, min_n: int = MIN_HISTORY
) -> float | None:
    """How far the latest reading sits above its own recent average.

    Expressed in the values' own units, not standardised: a bridge that
    multiplies a gasoline move by an energy weight needs the move, and
    standardising it would throw away the very scale the weight is defined
    against.
    """
    if len(values) < min_n:
        return None
    history = values[-window - 1 : -1]
    if not history:
        return None
    return values[-1] - fmean(history)


def zscore(values: list[float], min_n: int = MIN_HISTORY) -> float | None:
    """Latest reading in standard deviations of its own recent history.

    Used where a driver has no natural conversion into the target's units
    (claims into payrolls, say), so its message has to be expressed as
    "unusual by this much" and converted by an explicit, configured weight.
    """
    if len(values) < min_n:
        return None
    history = values[:-1]
    spread = pstdev(history)
    if spread == 0:
        return None
    return (values[-1] - fmean(history)) / spread


def next_period(latest: date, frequency: str) -> date:
    """The period a forecast made after ``latest`` is aiming at."""
    if frequency == "monthly":
        year, month = (
            (latest.year + 1, 1) if latest.month == 12 else (latest.year, latest.month + 1)
        )
        return date(year, month, 1)
    if frequency == "quarterly":
        month = latest.month + 3
        year = latest.year + (month - 1) // 12
        return date(year, (month - 1) % 12 + 1, 1)
    raise ValueError(f"cannot step a {frequency!r} series to its next period")


def to_decimal(value: float | None, places: str = "0.0001") -> Decimal | None:
    """Round for storage. Forecasts are stored at a fixed precision so two
    runs of the same method on the same data compare equal."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(places))

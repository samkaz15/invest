"""Scoring forecasts against what actually printed.

Two decisions here carry most of the weight, and both are about honesty
rather than arithmetic.

**The actual is the first print, not the current value.** A forecaster is
predicting the figure that will be published. Scoring against a number
restated three months later marks them against a question nobody asked, and
worse, lets the target move under the scoreboard — the same value could
score differently depending on when the scoring ran. The first vintage is
fixed forever, so a score computed today and one computed next year agree.

**The comparison is always against the naive baseline.** "Our error was
0.08pp" means nothing alone. "Our error was 0.08pp where doing nothing
would have been 0.11pp" is a finding. That difference is stored as `skill`,
and it is the closest thing this project has to a verdict
(docs/EVALUATION.md §3).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mios.common.logutil import get_logger
from mios.config.forecast import TargetSpec
from mios.series.repo import ObservationRepo
from mios.storage.db import Database

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScoredForecast:
    forecast_id: str
    target_series_id: str
    target_period: date
    actual: float
    actual_vintage_at: datetime
    point_value: float
    baseline_value: float
    error: float
    baseline_error: float
    skill: float
    direction_hit: bool | None
    upside_prob: float | None
    days_ahead: int
    method_version: str


@dataclass
class ScoringReport:
    scored: int = 0
    unresolved: int = 0  # forecasts whose period has not printed yet
    already_scored: int = 0


def first_print(
    repo: ObservationRepo, series_id: str, period: date, as_of: datetime
) -> tuple[float, datetime] | None:
    """The earliest published figure for ``period``, and when it appeared.

    ``as_of`` bounds the search so scoring can itself be replayed at a past
    instant without seeing prints that had not happened yet.
    """
    history = repo.revisions(series_id, period)
    for observation in history:  # oldest vintage first
        if observation.vintage_at > as_of:
            break
        if observation.value is not None:
            return float(observation.value), observation.vintage_at
    return None


def actual_change(
    repo: ObservationRepo,
    spec: TargetSpec,
    period: date,
    as_of: datetime,
) -> tuple[float, datetime] | None:
    """The realised value in the same units the forecast was made in.

    A forecast of core CPI is a month-over-month percent change, so the
    actual has to be built the same way — from the period's first print
    against the *previous* period as it stood when that print appeared.
    Using today's revised previous period would mix vintages and quietly
    change the answer every time the scoring job re-ran.
    """
    current = first_print(repo, spec.series_id, period, as_of)
    if current is None:
        return None
    value, vintage = current

    previous_rows = repo.as_of(spec.series_id, vintage, end=_previous_period(period))
    usable = [row for row in previous_rows if row.value is not None]
    if not usable:
        return None
    previous = float(usable[-1].value or Decimal(0))

    if spec.transform == "pct_change":
        if previous == 0:
            return None
        return value / previous - 1, vintage
    return value - previous, vintage


def _previous_period(period: date) -> date:
    year, month = (period.year - 1, 12) if period.month == 1 else (period.year, period.month - 1)
    return date(year, month, 1)


def score(
    forecast: dict[str, Any],
    actual: float,
    actual_vintage_at: datetime,
) -> ScoredForecast:
    """Turn one forecast and its realised value into a scored row."""
    point = float(forecast["point_value"])
    baseline = float(forecast["baseline_value"])
    error = actual - point
    baseline_error = actual - baseline

    adjustment = point - baseline
    if adjustment == 0:
        # The forecast made no directional call. An abstention is not a
        # wrong answer, and counting it as one would reward never leaving
        # the baseline.
        direction_hit: bool | None = None
    else:
        direction_hit = (adjustment > 0) == (baseline_error > 0)

    return ScoredForecast(
        forecast_id=forecast["forecast_id"],
        target_series_id=forecast["target_series_id"],
        target_period=forecast["target_period"],
        actual=actual,
        actual_vintage_at=actual_vintage_at,
        point_value=point,
        baseline_value=baseline,
        error=error,
        baseline_error=baseline_error,
        skill=abs(baseline_error) - abs(error),
        direction_hit=direction_hit,
        upside_prob=(
            float(forecast["upside_prob"]) if forecast["upside_prob"] is not None else None
        ),
        days_ahead=max(0, (actual_vintage_at - forecast["predicted_at"]).days),
        method_version=forecast["method_version"],
    )


class Scorer:
    def __init__(
        self,
        db: Database,
        observations: ObservationRepo,
        targets: dict[str, TargetSpec],
    ) -> None:
        self._db = db
        self._observations = observations
        self._targets = targets

    def run(self, as_of: datetime) -> ScoringReport:
        """Score every forecast whose period has since printed.

        Idempotent: a forecast already in ``forecast_errors`` is left alone,
        so the job can run daily without rewriting evidence.
        """
        report = ScoringReport()
        done = {
            row["forecast_id"] for row in self._db.query("SELECT forecast_id FROM forecast_errors")
        }
        pending = self._db.query(
            "SELECT * FROM predictions WHERE predicted_at <= %(a)s ORDER BY predicted_at",
            {"a": as_of},
        )
        for forecast in pending:
            if forecast["forecast_id"] in done:
                report.already_scored += 1
                continue
            spec = self._targets.get(forecast["target_series_id"])
            if spec is None or forecast["point_value"] is None:
                report.unresolved += 1
                continue
            realised = actual_change(self._observations, spec, forecast["target_period"], as_of)
            if realised is None:
                report.unresolved += 1
                continue
            actual, vintage = realised
            self._store(score(forecast, actual, vintage))
            report.scored += 1

        logger.info(
            "validate: scored=%d unresolved=%d already_scored=%d",
            report.scored,
            report.unresolved,
            report.already_scored,
        )
        return report

    def _store(self, scored: ScoredForecast) -> None:
        self._db.execute(
            """
            INSERT INTO forecast_errors (forecast_id, target_series_id, target_period,
                actual, actual_vintage_at, point_value, baseline_value, error, abs_error,
                baseline_error, skill, direction_hit, upside_prob, days_ahead, method_version)
            VALUES (%(forecast_id)s, %(target_series_id)s, %(target_period)s, %(actual)s,
                %(actual_vintage_at)s, %(point_value)s, %(baseline_value)s, %(error)s,
                %(abs_error)s, %(baseline_error)s, %(skill)s, %(direction_hit)s,
                %(upside_prob)s, %(days_ahead)s, %(method_version)s)
            ON CONFLICT (forecast_id) DO NOTHING
            """,
            {
                "forecast_id": scored.forecast_id,
                "target_series_id": scored.target_series_id,
                "target_period": scored.target_period,
                "actual": scored.actual,
                "actual_vintage_at": scored.actual_vintage_at,
                "point_value": scored.point_value,
                "baseline_value": scored.baseline_value,
                "error": scored.error,
                "abs_error": abs(scored.error),
                "baseline_error": scored.baseline_error,
                "skill": scored.skill,
                "direction_hit": scored.direction_hit,
                "upside_prob": scored.upside_prob,
                "days_ahead": scored.days_ahead,
                "method_version": scored.method_version,
            },
        )

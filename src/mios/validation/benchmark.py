"""Scoring the outside forecasters, and comparing them with MIOS.

`forecast_errors` answers "did the drivers beat doing nothing?". This
answers the question that actually decides whether the project was worth
building: **did it beat what was already public and free on the same
morning?** Beating the naive baseline is routine. Beating a Federal Reserve
Bank's published nowcast of the same print is a claim worth making, and
failing to is a finding worth knowing early rather than in year two.

Two things make the comparison honest, and without either it would be
decoration:

**The same actual and the same baseline.** Both sides are scored against the
period's first print, and against a naive baseline recomputed at each
forecast's own vintage with the same function the forecaster itself uses
(`prediction.features.changes_of` + `trailing_mean`). Two definitions that
drifted apart would turn every verdict here into an artefact of the drift.

**The same information.** A MIOS forecast made 30 days out is not comparable
to a nowcast published the morning of the release. Pairing therefore takes
the provider's newest forecast that was *knowable at the MIOS forecast's own
as-of instant* — never a later one, however much closer in time it sits.
"""

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean
from typing import Any

from mios.common.logutil import get_logger
from mios.config.forecast import TargetSpec
from mios.prediction.external import ExternalForecastRepo
from mios.prediction.features import changes_of, load, next_period, trailing_mean
from mios.series.repo import ObservationRepo
from mios.storage.db import Database
from mios.validation.metrics import MIN_SAMPLE
from mios.validation.scoring import actual_change

logger = get_logger(__name__)


@dataclass
class BenchmarkReport:
    scored: int = 0
    unresolved: int = 0  # period has not printed, or no baseline could be built
    already_scored: int = 0


@dataclass(frozen=True)
class Comparison:
    """MIOS against one provider, on the periods where both had an opinion."""

    provider_id: str
    target_series_id: str
    n: int
    mios_mae: float | None
    provider_mae: float | None
    baseline_mae: float | None
    #: provider_mae - mios_mae. Positive means MIOS was closer on these
    #: periods. This is the verdict; everything else here is context for it.
    edge: float | None
    sufficient: bool

    @property
    def beats_provider(self) -> bool | None:
        if self.edge is None or not self.sufficient:
            return None
        return self.edge > 0


def naive_baseline(
    repo: ObservationRepo, spec: TargetSpec, as_of: datetime, target_period: Any
) -> float | None:
    """The naive answer for ``target_period``, built only from data knowable at ``as_of``.

    The baseline is a trailing mean of the target's own recent changes, and
    it does not depend on how far out the period is — so it is the naive
    forecast for a period two months ahead just as much as for the next one.
    What it must never be is a baseline for a period that had already
    printed, which would score the provider against a number they could
    simply have read.
    """
    target = load(repo, spec.series_id, as_of)
    if target.latest_period is None:
        return None
    if next_period(target.latest_period, spec.frequency) > target_period:
        # The period was already published when this forecast was made.
        return None
    changes = changes_of(target, spec)
    return trailing_mean(changes, window=spec.baseline_window)


class BenchmarkScorer:
    def __init__(
        self,
        db: Database,
        observations: ObservationRepo,
        external: ExternalForecastRepo,
        targets: dict[str, TargetSpec],
    ) -> None:
        self._db = db
        self._observations = observations
        self._external = external
        self._targets = targets

    def run(self, as_of: datetime) -> BenchmarkReport:
        """Score every outside forecast whose period has since printed.

        Idempotent, like the MIOS scorer: a forecast already in
        ``external_forecast_errors`` is left alone. Evidence is never
        rewritten, not even with the same values.
        """
        report = BenchmarkReport()
        for row in self._external.unscored():
            if row["vintage_at"] > as_of:
                report.unresolved += 1
                continue
            spec = self._targets.get(row["target_series_id"])
            if spec is None:
                report.unresolved += 1
                continue
            realised = actual_change(self._observations, spec, row["target_period"], as_of)
            baseline = naive_baseline(
                self._observations, spec, row["vintage_at"], row["target_period"]
            )
            if realised is None or baseline is None:
                report.unresolved += 1
                continue
            actual, vintage = realised
            self._store(row, actual, vintage, baseline)
            report.scored += 1

        logger.info(
            "benchmark: scored=%d unresolved=%d",
            report.scored,
            report.unresolved,
        )
        return report

    def _store(
        self, row: dict[str, Any], actual: float, actual_vintage_at: datetime, baseline: float
    ) -> None:
        point = float(row["point_value"])
        error = actual - point
        baseline_error = actual - baseline
        adjustment = point - baseline
        direction_hit = None if adjustment == 0 else (adjustment > 0) == (baseline_error > 0)
        self._db.execute(
            """
            INSERT INTO external_forecast_errors (external_forecast_id, provider_id,
                target_series_id, target_period, actual, actual_vintage_at, point_value,
                baseline_value, error, abs_error, baseline_error, skill, direction_hit,
                days_ahead)
            VALUES (%(external_forecast_id)s, %(provider_id)s, %(target_series_id)s,
                %(target_period)s, %(actual)s, %(actual_vintage_at)s, %(point_value)s,
                %(baseline_value)s, %(error)s, %(abs_error)s, %(baseline_error)s,
                %(skill)s, %(direction_hit)s, %(days_ahead)s)
            ON CONFLICT (external_forecast_id) DO NOTHING
            """,
            {
                "external_forecast_id": row["external_forecast_id"],
                "provider_id": row["provider_id"],
                "target_series_id": row["target_series_id"],
                "target_period": row["target_period"],
                "actual": actual,
                "actual_vintage_at": actual_vintage_at,
                "point_value": point,
                "baseline_value": baseline,
                "error": error,
                "abs_error": abs(error),
                "baseline_error": baseline_error,
                "skill": abs(baseline_error) - abs(error),
                "direction_hit": direction_hit,
                "days_ahead": max(0, (actual_vintage_at - row["vintage_at"]).days),
            },
        )


class BenchmarkReader:
    """The head-to-head, computed only from forecasts formed on equal information."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def comparisons(self) -> list[Comparison]:
        rows = self._db.query(
            """
            SELECT x.provider_id,
                   x.target_series_id,
                   x.target_period,
                   x.abs_error       AS provider_abs_error,
                   x.baseline_value  AS provider_baseline,
                   m.abs_error       AS mios_abs_error,
                   m.baseline_error  AS mios_baseline_error
            FROM external_forecast_errors x
            JOIN predictions xp ON xp.forecast_id = (
                -- The MIOS forecast in force when this outside forecast
                -- became knowable: same target, same period, formed from
                -- data no newer than theirs. Pairing against a later MIOS
                -- forecast would hand MIOS information the provider did not
                -- have and call the result an edge.
                SELECT p.forecast_id FROM predictions p
                WHERE p.target_series_id = x.target_series_id
                  AND p.target_period = x.target_period
                  AND p.predicted_at <= (
                      SELECT f.vintage_at FROM external_forecasts f
                      WHERE f.external_forecast_id = x.external_forecast_id
                  )
                ORDER BY p.predicted_at DESC LIMIT 1
            )
            JOIN forecast_errors m ON m.forecast_id = xp.forecast_id
            ORDER BY x.provider_id, x.target_series_id, x.target_period
            """
        )

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault((row["provider_id"], row["target_series_id"]), []).append(row)

        out: list[Comparison] = []
        for (provider_id, series_id), group in sorted(grouped.items()):
            mios = [float(r["mios_abs_error"]) for r in group]
            provider = [float(r["provider_abs_error"]) for r in group]
            baseline = [abs(float(r["mios_baseline_error"])) for r in group]
            mios_mae = fmean(mios)
            provider_mae = fmean(provider)
            out.append(
                Comparison(
                    provider_id=provider_id,
                    target_series_id=series_id,
                    n=len(group),
                    mios_mae=mios_mae,
                    provider_mae=provider_mae,
                    baseline_mae=fmean(baseline),
                    edge=provider_mae - mios_mae,
                    sufficient=len(group) >= MIN_SAMPLE,
                )
            )
        return out

    def coverage(self) -> dict[str, int]:
        row = self._db.query_one(
            """
            SELECT (SELECT count(*) FROM external_forecasts)        AS stored,
                   (SELECT count(*) FROM external_forecast_errors)  AS scored,
                   (SELECT count(DISTINCT provider_id) FROM external_forecasts) AS providers
            """
        )
        return {k: int(v) for k, v in (row or {}).items()}

"""Reading the scoreboard.

Every metric here refuses to report on too few observations. That is not
caution for its own sake: a "directional accuracy of 100%" computed from two
scored forecasts is worse than no number, because it will be believed. The
minimum sample is stated on each result so a reader can see how much weight
it carries (docs/EVALUATION.md §1).

Nothing here is a score of MIOS in the abstract. Every figure is relative to
the naive baseline, because "our MAE was 0.08pp" alone is unfalsifiable
decoration.
"""

from dataclasses import dataclass
from statistics import fmean
from typing import Any

from mios.storage.db import Database

#: Below this many scored forecasts, an accuracy figure is an anecdote.
MIN_SAMPLE = 10

#: Calibration buckets for P(above baseline).
CALIBRATION_BINS: list[tuple[float, float]] = [
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.01),
]


@dataclass(frozen=True)
class Accuracy:
    """How one target has done, at one horizon band."""

    target_series_id: str
    horizon: str
    n: int
    mae: float | None
    rmse: float | None
    bias: float | None  # mean signed error; a persistent sign is a fixable flaw
    baseline_mae: float | None
    #: Mean of abs(baseline error) - abs(error). Positive means the drivers
    #: are earning their keep. This is the number the project lives or dies by.
    skill: float | None
    directional_accuracy: float | None
    sufficient: bool  # whether n cleared MIN_SAMPLE

    @property
    def beats_naive(self) -> bool | None:
        if self.skill is None or not self.sufficient:
            return None
        return self.skill > 0


@dataclass(frozen=True)
class CalibrationBin:
    """One band of stated probabilities against what actually happened."""

    lower: float
    upper: float
    n: int
    stated: float | None  # mean probability claimed in this band
    realised: float | None  # fraction that actually landed above baseline

    @property
    def overconfident(self) -> bool | None:
        if self.stated is None or self.realised is None or self.n < MIN_SAMPLE:
            return None
        return self.stated > self.realised


def _horizon_band(days: int) -> str:
    """Accuracy at 30 days out and at 1 day out are different questions."""
    if days <= 3:
        return "0-3d"
    if days <= 10:
        return "4-10d"
    if days <= 30:
        return "11-30d"
    return "31d+"


class MetricsReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _rows(self, target_series_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM forecast_errors"
        params: dict[str, Any] = {}
        if target_series_id is not None:
            sql += " WHERE target_series_id = %(t)s"
            params["t"] = target_series_id
        return self._db.query(sql + " ORDER BY target_period, days_ahead", params)

    def accuracy(self, target_series_id: str | None = None) -> list[Accuracy]:
        """MAE / RMSE / bias / skill / directional accuracy, per target and horizon."""
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in self._rows(target_series_id):
            key = (row["target_series_id"], _horizon_band(int(row["days_ahead"])))
            grouped.setdefault(key, []).append(row)

        results: list[Accuracy] = []
        for (target, horizon), rows in sorted(grouped.items()):
            errors = [float(r["error"]) for r in rows]
            baseline_errors = [float(r["baseline_error"]) for r in rows]
            skills = [float(r["skill"]) for r in rows]
            calls = [r["direction_hit"] for r in rows if r["direction_hit"] is not None]
            n = len(rows)
            sufficient = n >= MIN_SAMPLE
            results.append(
                Accuracy(
                    target_series_id=target,
                    horizon=horizon,
                    n=n,
                    mae=fmean(abs(e) for e in errors) if sufficient else None,
                    rmse=(fmean(e * e for e in errors) ** 0.5) if sufficient else None,
                    bias=fmean(errors) if sufficient else None,
                    baseline_mae=fmean(abs(e) for e in baseline_errors) if sufficient else None,
                    skill=fmean(skills) if sufficient else None,
                    directional_accuracy=(
                        sum(1 for c in calls if c) / len(calls) if sufficient and calls else None
                    ),
                    sufficient=sufficient,
                )
            )
        return results

    def calibration(self, target_series_id: str | None = None) -> list[CalibrationBin]:
        """Stated probability against realised frequency.

        "When we said 70% the actual came in above baseline 55% of the time"
        is the finding that makes a probability worth stating at all. A
        systematic gap means the method is overconfident and the fix is a
        change to the probability function, not a mystery.
        """
        rows = [r for r in self._rows(target_series_id) if r["upside_prob"] is not None]
        bins: list[CalibrationBin] = []
        for lower, upper in CALIBRATION_BINS:
            in_bin = [r for r in rows if lower <= float(r["upside_prob"]) < upper]
            if not in_bin:
                bins.append(CalibrationBin(lower, upper, 0, None, None))
                continue
            stated = fmean(float(r["upside_prob"]) for r in in_bin)
            realised = sum(1 for r in in_bin if float(r["baseline_error"]) > 0) / len(in_bin)
            bins.append(CalibrationBin(lower, upper, len(in_bin), stated, realised))
        return bins

    def coverage(self) -> dict[str, int]:
        """How much evidence exists at all — the first thing to look at.

        Until these numbers are in the dozens, every metric above is an
        anecdote, and saying so plainly is more useful than a precise-looking
        table built on four rows.
        """
        row = self._db.query_one(
            """
            SELECT count(*) AS scored,
                   count(DISTINCT target_series_id) AS targets,
                   count(DISTINCT target_period) AS periods
            FROM forecast_errors
            """
        )
        pending = self._db.query_one(
            """
            SELECT count(*) AS n FROM predictions p
            WHERE NOT EXISTS (
                SELECT 1 FROM forecast_errors e WHERE e.forecast_id = p.forecast_id
            )
            """
        )
        return {
            "scored": int(row["scored"]) if row else 0,
            "targets": int(row["targets"]) if row else 0,
            "periods": int(row["periods"]) if row else 0,
            "awaiting_actuals": int(pending["n"]) if pending else 0,
        }

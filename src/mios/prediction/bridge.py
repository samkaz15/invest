"""The forecasting method, shared by every target.

A forecast here is deliberately boring::

    point = baseline + Σ (driver reading × configured weight)

The baseline is the naive answer — the trailing mean of the target's own
recent changes — and it is stored alongside the forecast so "did the
drivers earn their keep?" is answerable from the row. If the adjustment is
always near zero, the drivers are decoration and the evaluation will say
so.

Why not fit the weights? Because there is nothing yet to fit them on. A
regression estimated today would be fitted to a handful of periods and
would look far better in sample than it could ever perform out of it. The
weights start as stated priors, each with a written justification, and the
project earns the right to re-estimate them once enough forecast errors
have accumulated (docs/EVALUATION.md §3). A weight nobody can defend is
exactly the untraceable score this repository already deleted once.

Two kinds of driver, and the difference matters:

* **Elastic** — the driver converts into the target's units by a published
  basket weight. Gasoline into headline CPI is near-mechanical: the pump
  price is a known share of the index.
* **Standardised** — no natural conversion exists (jobless claims into
  payrolls), so the driver is expressed in standard deviations of its own
  history and converted by a prior. These are the weights most in need of
  re-estimation, and they are marked as such in config.
"""

from dataclasses import dataclass
from datetime import datetime

from mios.common.ids import IdKind, make_dated_id, slugify
from mios.common.logutil import get_logger
from mios.config.forecast import DriverSpec, TargetSpec
from mios.prediction.features import (
    MIN_HISTORY,
    Series,
    deviation_from_trend,
    diff_series,
    load,
    mom_series,
    next_period,
    trailing_mean,
    zscore,
)
from mios.prediction.models import Driver, Forecast
from mios.prediction.probability import (
    baseline_error_spread,
    confidence_from,
    directional_probabilities,
)
from mios.series.repo import ObservationRepo

logger = get_logger(__name__)

VERSION = "bridge/v1"

#: A contradicting driver is only worth naming once it moves the call by
#: this share of the target's adjustment cap.
CONTRADICTION_THRESHOLD = 0.05


@dataclass
class _Assembly:
    """Working state while a forecast is being built."""

    drivers: list[Driver]
    gaps: list[str]


def _target_changes(series: Series, spec: TargetSpec) -> list[float]:
    """The target expressed as the thing actually being forecast.

    An index (CPI) is forecast as a month-over-month percent change; a
    level (payrolls) as a month-over-month difference. Forecasting the
    level itself would make a 0.3% miss look like a rounding error next to
    a 325-point index.
    """
    return mom_series(series) if spec.transform == "pct_change" else diff_series(series)


def _driver_reading(
    repo: ObservationRepo, driver: DriverSpec, as_of: datetime
) -> tuple[float | None, str]:
    """One driver's number and the sentence explaining it."""
    series = load(repo, driver.series_id, as_of)
    if len(series) < MIN_HISTORY:
        return None, f"{driver.series_id}: history n={len(series)} < {MIN_HISTORY}"

    if driver.mode == "elastic":
        changes = mom_series(series)
        reading = deviation_from_trend(changes, window=driver.window)
        if reading is None:
            return None, f"{driver.series_id}: not enough change history"
        return reading, (
            f"{driver.label} ran {reading:+.2%} against its {driver.window}-period average"
        )

    changes = _standardised_input(series, driver)
    reading = zscore(changes)
    if reading is None:
        return None, f"{driver.series_id}: no usable spread in history"
    return reading, f"{driver.label} sits {reading:+.2f}σ from its own recent history"


def _standardised_input(series: Series, driver: DriverSpec) -> list[float]:
    if driver.transform == "pct_change":
        return mom_series(series)
    if driver.transform == "diff":
        return diff_series(series)
    return list(series.values)


def forecast_target(
    repo: ObservationRepo,
    spec: TargetSpec,
    as_of: datetime,
    predicted_at: datetime,
) -> Forecast | None:
    """Build one forecast, or nothing if the target itself is unreadable.

    Returning ``None`` rather than a zero-confidence guess is deliberate:
    if the target series has no usable history at ``as_of``, there is
    nothing to forecast from, and recording a number anyway would put a
    fabricated row into the one table that must never contain one.
    """
    target = load(repo, spec.series_id, as_of)
    if target.latest_period is None:
        logger.warning("%s: no observations as of %s", spec.series_id, as_of.isoformat())
        return None

    changes = _target_changes(target, spec)
    baseline = trailing_mean(changes, window=spec.baseline_window)
    if baseline is None:
        logger.warning(
            "%s: only %d change(s) of history — below the baseline window",
            spec.series_id,
            len(changes),
        )
        return None

    assembly = _Assembly(drivers=[], gaps=[])
    for driver_spec in spec.drivers:
        reading, note = _driver_reading(repo, driver_spec, as_of)
        if reading is None:
            assembly.gaps.append(note)
            continue
        contribution = reading * driver_spec.weight
        assembly.drivers.append(
            Driver(
                series_id=driver_spec.series_id,
                label=driver_spec.label,
                value=round(reading, 6),
                weight=driver_spec.weight,
                contribution=round(contribution, 6),
                rationale=f"{note} → {contribution:+.4f} {spec.unit_label}",
            )
        )

    adjustment = sum(d.contribution for d in assembly.drivers)
    # A bound the config sets per target. Without it one wild driver reading
    # — a gasoline spike, a claims week distorted by a hurricane — can drag
    # the call further than the method has any business claiming.
    capped = max(-spec.max_adjustment, min(spec.max_adjustment, adjustment))
    if capped != adjustment:
        assembly.gaps.append(
            f"adjustment {adjustment:+.4f} capped at ±{spec.max_adjustment} "
            "(one driver dominating; see drivers for which)"
        )
    point = baseline + capped

    spread = baseline_error_spread(changes, window=spec.baseline_window)
    upside, downside = directional_probabilities(capped, spread)
    if spread is None:
        assembly.gaps.append(
            f"baseline error spread: only {max(0, len(changes) - spec.baseline_window)} "
            "past periods — probabilities withheld rather than invented"
        )

    period = next_period(target.latest_period, spec.frequency)
    # A driver only counts as contradicting if it is pulling with some
    # force. Listing every input whose contribution rounds to zero buries
    # the one real disagreement under a page of noise, which is the same
    # failure as not reporting disagreement at all.
    material = spec.max_adjustment * CONTRADICTION_THRESHOLD
    net_direction = 1 if capped > 0 else (-1 if capped < 0 else 0)
    contradictions = [
        f"{d.label} points the other way ({d.contribution:+.4f} {spec.unit_label})"
        for d in assembly.drivers
        if net_direction != 0 and d.direction == -net_direction and abs(d.contribution) >= material
    ]

    return Forecast(
        forecast_id=make_dated_id(
            IdKind.FORECAST,
            predicted_at.date().isoformat(),
            f"{slugify(spec.series_id.removeprefix('ser_'))}-{period.isoformat()}",
        ),
        target_series_id=spec.series_id,
        target_period=period,
        predicted_at=predicted_at,
        as_of=as_of,
        point_value=round(point, 6),
        baseline_value=round(baseline, 6),
        upside_prob=upside,
        downside_prob=downside,
        confidence=confidence_from(
            available=len(assembly.drivers),
            missing=len(spec.drivers) - len(assembly.drivers),
            history=len(changes),
            needed=spec.baseline_window * 2,
        ),
        method_version=VERSION,
        drivers=assembly.drivers,
        contradictions=contradictions,
        data_gaps=assembly.gaps,
    )

"""Where the upside/downside probabilities come from.

BIOS produced probabilities by a linear transform of a score and its own
docstring admitted they were not statistics (docs/REPOSITORY_AUDIT.md §8
U-12). Measuring the calibration of that would have measured the slope of a
formula.

These mean something narrower but real: **P(the actual lands above the
naive baseline)**, given how far the drivers push away from it and how
wide this target's baseline errors have historically been. Both inputs are
measured from stored data, so the number is reproducible and, once enough
releases have landed, checkable against outcomes (docs/EVALUATION.md §4).

When the history is too short to estimate a spread, the answer is ``None``.
An unknown probability is a real answer; 50% would be a fabricated one.
"""

import math
from statistics import fmean, pstdev

#: Below this many past periods, the spread of baseline errors is not a
#: distribution, it is a handful of numbers.
MIN_ERROR_SAMPLE = 12

#: Probabilities are clamped away from the extremes. Not cosmetics: the
#: normal assumption below is thinnest exactly in the tails, the weights
#: feeding the adjustment are stated priors rather than fitted values, and
#: nothing here has been calibrated against a single realised outcome yet.
#: "99%" would be a claim this method has not earned, and CONSTITUTION.md
#: Art.5 forbids stating a forecast as a certainty. The bound relaxes when
#: there is calibration evidence to relax it with (docs/EVALUATION.md §4).
PROBABILITY_BOUND = 0.05


def normal_cdf(z: float) -> float:
    """Standard normal CDF, via the error function in the stdlib.

    No new dependency for one integral (CONSTITUTION.md Art.8-2).
    """
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def baseline_error_spread(
    actuals: list[float], window: int, min_n: int = MIN_ERROR_SAMPLE
) -> float | None:
    """How wrong the naive forecast has been, historically.

    The naive forecast for a period is the trailing mean of the ``window``
    periods before it. Replaying that over the stored history gives a
    distribution of errors whose spread is what a deviation from baseline
    has to be judged against — a +0.1pp push means a lot for a series whose
    baseline is usually right within 0.05pp and very little for one that
    routinely misses by 0.3pp.
    """
    errors: list[float] = []
    for i in range(window, len(actuals)):
        baseline = fmean(actuals[i - window : i])
        errors.append(actuals[i] - baseline)
    if len(errors) < min_n:
        return None
    spread = pstdev(errors)
    return spread if spread > 0 else None


def directional_probabilities(
    adjustment: float, error_spread: float | None
) -> tuple[float | None, float | None]:
    """P(actual above baseline), P(actual below), from the drivers' push.

    Treats the baseline error as normal around the adjusted call. That is
    an assumption, and a checkable one: if the resulting probabilities turn
    out systematically overconfident, the calibration curve in
    docs/EVALUATION.md §4 will show it, and the fix is a change to this
    function rather than a mystery.
    """
    if error_spread is None:
        return None, None
    upside = normal_cdf(adjustment / error_spread)
    upside = max(PROBABILITY_BOUND, min(1.0 - PROBABILITY_BOUND, upside))
    return round(upside, 3), round(1.0 - upside, 3)


def confidence_from(available: int, missing: int, history: int, needed: int) -> float:
    """How much of what this method wanted, it actually had.

    Two things degrade a forecast independently: inputs that were missing,
    and history too short to characterise the target. Both are folded in,
    and the result is stored, so a forecast made on a thin day is visibly
    thin rather than quietly indistinguishable from a complete one.
    """
    if available == 0:
        return 0.1
    coverage = available / (available + missing)
    depth = min(1.0, history / needed) if needed > 0 else 1.0
    return round(max(0.1, min(0.95, coverage * depth)), 2)

"""Statistics helpers with the minimum-sample discipline built in
(IES §5.3, §8.3): below the floor we return None — callers must record a
data gap, never fabricate a reading from thin history."""

import statistics
from collections.abc import Sequence

MIN_SAMPLE = 30


def zscore(history: Sequence[float], current: float, min_n: int = MIN_SAMPLE) -> float | None:
    if len(history) < min_n:
        return None
    mean = statistics.fmean(history)
    stdev = statistics.pstdev(history)
    if stdev == 0:
        return 0.0
    return (current - mean) / stdev


def percentile_rank(
    history: Sequence[float], current: float, min_n: int = MIN_SAMPLE
) -> float | None:
    """Fraction of history strictly below current (0..1)."""
    if len(history) < min_n:
        return None
    below = sum(1 for value in history if value < current)
    return below / len(history)


def pct_change(old: float, new: float) -> float | None:
    if old == 0:
        return None
    return (new - old) / old

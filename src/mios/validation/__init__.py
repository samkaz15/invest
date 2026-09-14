"""Validation — whether the forecasts are any good.

CONSTITUTION.md Art.2 defines success as being able to answer, in six
months, whether MIOS actually helps forecast CPI and NFP. This package is
where that answer comes from; everything upstream is machinery for filling
its table.

Two rules shape it. The actual is the **first print**, because that is what
a forecaster was predicting and because it never moves afterwards. And every
figure is stated **relative to the naive baseline**, because an absolute
error alone is unfalsifiable.
"""

from mios.validation.metrics import (
    MIN_SAMPLE,
    Accuracy,
    CalibrationBin,
    MetricsReader,
)
from mios.validation.scoring import ScoredForecast, Scorer, ScoringReport, actual_change, score

__all__ = [
    "MIN_SAMPLE",
    "Accuracy",
    "CalibrationBin",
    "MetricsReader",
    "ScoredForecast",
    "Scorer",
    "ScoringReport",
    "actual_change",
    "score",
]

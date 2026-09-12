"""Prediction — the CPI and NFP forecasts, and their vintages.

The most important package in the repository, and the smallest reasonable
version of itself. A forecast is a naive baseline plus a bounded,
configured adjustment from leading indicators, stored once per day and
never overwritten, with every input and weight recorded alongside it.

LLMs are not involved. Numbers come from the database (CONSTITUTION.md
Art.5); the language layer's job, later, is to explain these — never to
produce them.
"""

from mios.prediction.bridge import VERSION, forecast_target
from mios.prediction.features import Series, load
from mios.prediction.models import Driver, Forecast
from mios.prediction.probability import (
    baseline_error_spread,
    directional_probabilities,
    normal_cdf,
)
from mios.prediction.repo import ForecastRepo

__all__ = [
    "VERSION",
    "Driver",
    "Forecast",
    "ForecastRepo",
    "Series",
    "baseline_error_spread",
    "directional_probabilities",
    "forecast_target",
    "load",
    "normal_cdf",
]

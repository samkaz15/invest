"""Analyzer framework.

An analyzer is a pure function over market history: it receives the
snapshot rows (ascending by ts) plus context and returns a
DimensionReport. No I/O inside analyzers — everything they saw is in
their inputs, so runs are reproducible and unit-testable.
"""

from datetime import datetime
from typing import Any, Protocol

from bios.analysis.models import DimensionReport

# A snapshot row as stored: {"ts": datetime, "price_usd": ..., "asset_metrics": {...}}
SnapshotRow = dict[str, Any]


class DimensionAnalyzer(Protocol):
    dimension_name: str

    def analyze(
        self, asset_id: str, as_of: datetime, history: list[SnapshotRow]
    ) -> DimensionReport: ...


def metric_series(history: list[SnapshotRow], metric: str) -> list[float]:
    """Extract one metric's series from snapshot rows (missing rows skipped)."""
    series: list[float] = []
    for row in history:
        value = row.get("asset_metrics", {}).get(metric)
        if value is None and metric in ("price_usd", "volume_24h_usd"):
            value = row.get(metric)
        if value is not None:
            series.append(float(value))
    return series


def latest_metric(history: list[SnapshotRow], metric: str) -> float | None:
    for row in reversed(history):
        value = row.get("asset_metrics", {}).get(metric)
        if value is None and metric in ("price_usd", "volume_24h_usd"):
            value = row.get(metric)
        if value is not None:
            return float(value)
    return None

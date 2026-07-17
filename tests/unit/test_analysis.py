"""Analyzer unit tests: pure functions over synthetic snapshot history."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bios.analysis.base import SnapshotRow
from bios.analysis.derivatives import DerivativesAnalyzer
from bios.analysis.models import Signal, compose_report
from bios.analysis.news_flow import NewsFlowAnalyzer
from bios.analysis.onchain import OnchainAnalyzer
from bios.analysis.stats import pct_change, percentile_rank, zscore
from bios.common.labels import ClaimLabel, Dimension

AS_OF = datetime(2026, 7, 15, 6, 0, tzinfo=UTC)


def _history(n: int, **series: list[float] | float) -> list[SnapshotRow]:
    """Build n hourly snapshots; metrics given as constants or full lists."""
    rows: list[SnapshotRow] = []
    for i in range(n):
        metrics: dict[str, Any] = {}
        for name, values in series.items():
            metrics[name] = values[i] if isinstance(values, list) else values
        rows.append(
            {
                "ts": AS_OF - timedelta(hours=n - i),
                "price_usd": 60000.0,
                "asset_metrics": metrics,
            }
        )
    return rows


# ---------------------------------------------------------------- stats


def test_min_sample_discipline() -> None:
    assert zscore([1.0] * 29, 1.0) is None  # below floor -> no reading
    assert percentile_rank([1.0] * 29, 1.0) is None
    assert zscore([1.0] * 30, 1.0) == 0.0
    assert percentile_rank(list(map(float, range(100))), 95.0) == 0.95
    assert pct_change(0.0, 5.0) is None


# ----------------------------------------------------------- derivatives


def test_funding_extreme_high_fires_with_history() -> None:
    history = _history(60, funding_rate=[0.0001] * 59 + [0.01], open_interest=100.0)
    report = DerivativesAnalyzer().analyze("ent_asset_btc", AS_OF, history)
    ids = [s.signal_id for s in report.signals]
    assert "derivatives.funding_extreme_high" in ids
    assert report.score < 0
    assert report.dimension is Dimension.DERIVATIVES


def test_thin_history_yields_gaps_not_guesses() -> None:
    report = DerivativesAnalyzer().analyze(
        "ent_asset_btc", AS_OF, _history(2, funding_rate=0.01, open_interest=100.0)
    )
    assert report.score == 0
    assert report.conviction <= 0.5
    assert any("funding_rate: history" in g for g in report.data_gaps)


def test_oi_flush_scores_positive() -> None:
    oi = [100.0] * 40 + [80.0] * 20  # -20% over the last day of hourly points
    report = DerivativesAnalyzer().analyze(
        "ent_asset_btc", AS_OF, _history(60, funding_rate=0.0001, open_interest=oi)
    )
    shift = [s for s in report.signals if s.signal_id == "derivatives.oi_shift_24h"]
    assert shift and shift[0].points > 0  # leverage reset reads constructive


# --------------------------------------------------------------- onchain


def test_hashrate_drawdown_detected() -> None:
    hr = [100.0] * 7 + [85.0] * 7
    report = OnchainAnalyzer().analyze("ent_asset_btc", AS_OF, _history(14, hash_rate=hr))
    assert any(s.signal_id == "onchain.hashrate_drawdown" for s in report.signals)
    # unavailable paid metrics are declared as gaps, not silently absent
    assert any("mvrv" in g for g in report.data_gaps)


# ------------------------------------------------------------- news flow


@pytest.mark.parametrize(("fng", "expected"), [(10.0, 10), (28.0, 5), (50.0, 0), (90.0, -10)])
def test_fear_greed_bands(fng: float, expected: int) -> None:
    report = NewsFlowAnalyzer(queue_stats={"pending": 3}).analyze(
        "ent_asset_btc", AS_OF, _history(1, fear_greed=fng)
    )
    band = [s for s in report.signals if s.signal_id == "news.fear_greed_band"]
    assert band and band[0].points == expected
    assert band[0].label is ClaimLabel.INFERENCE  # contrarian read is inference


# --------------------------------------------------------------- compose


def test_compose_report_conviction_reflects_completeness() -> None:
    signals = [
        Signal(signal_id="x.a", value=1.0, points=60, label=ClaimLabel.FACT, rationale="r"),
        Signal(signal_id="x.b", value=1.0, points=60, label=ClaimLabel.FACT, rationale="r"),
    ]
    full = compose_report(Dimension.MACRO, "ent_asset_btc", AS_OF, signals, [], "v1")
    assert full.score == 100  # clipped
    assert full.conviction == 0.9
    empty = compose_report(Dimension.MACRO, "ent_asset_btc", AS_OF, [], ["gap"], "v1")
    assert empty.score == 0 and empty.conviction == 0.1

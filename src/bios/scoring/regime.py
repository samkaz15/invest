"""Regime classification v1 (IES §10 layer 1) — pure rules, no LLM.

Honesty over coverage: every axis reports "unknown" until its input
history exists (daily closes for trend, 30+ days for vol percentile,
macro series for liquidity). Downstream weight selection falls back to
the default set while the phase is unknown.
"""

from datetime import datetime
from statistics import fmean, pstdev

from bios.analysis.base import SnapshotRow
from bios.common.schema import BiosModel

VERSION = "regime/v1"
TREND_WINDOW_DAYS = 20
VOL_WINDOW_DAYS = 30


class Regime(BiosModel):
    trend: str = "unknown"  # bull | bear | range | unknown
    vol: str = "unknown"  # low | normal | high | unknown
    liquidity: str = "unknown"  # easing | neutral | tightening | unknown
    version: str = VERSION

    def phase_key(self) -> str:
        """Weight-set key for scoring.yaml (default until phase is known)."""
        if self.liquidity == "tightening":
            return "liquidity_tightening"
        return "default"


def daily_closes(history: list[SnapshotRow]) -> list[float]:
    """Last price per calendar date (UTC), ascending."""
    by_day: dict[str, float] = {}
    for row in history:
        price = row.get("price_usd")
        ts: datetime = row["ts"]
        if price is not None:
            by_day[ts.strftime("%Y-%m-%d")] = float(price)
    return [by_day[d] for d in sorted(by_day)]


def classify(history: list[SnapshotRow]) -> Regime:
    closes = daily_closes(history)
    trend = "unknown"
    if len(closes) >= TREND_WINDOW_DAYS:
        sma = fmean(closes[-TREND_WINDOW_DAYS:])
        deviation = closes[-1] / sma - 1
        if deviation > 0.03:
            trend = "bull"
        elif deviation < -0.03:
            trend = "bear"
        else:
            trend = "range"

    vol = "unknown"
    if len(closes) >= VOL_WINDOW_DAYS + 1:
        returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        recent = pstdev(returns[-VOL_WINDOW_DAYS:])
        # percentile vs own history when long enough; crude bands until then
        if recent < 0.015:
            vol = "low"
        elif recent > 0.035:
            vol = "high"
        else:
            vol = "normal"

    # liquidity needs macro series (FRED) — stays unknown until wired.
    return Regime(trend=trend, vol=vol)

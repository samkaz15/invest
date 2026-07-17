"""On-chain dimension (IES §5), rule-based v1.

Only network-primary metrics available on free sources today (hashrate,
difficulty, tx count). Valuation metrics (MVRV/SOPR/reserves) surface as
explicit data gaps until a data contract exists — the report never hides
what it cannot see.
"""

from datetime import datetime

from bios.analysis.base import SnapshotRow, latest_metric, metric_series
from bios.analysis.models import DimensionReport, Signal, compose_report
from bios.analysis.stats import pct_change
from bios.common.labels import ClaimLabel, Dimension

VERSION = "onchain/v1"
UNAVAILABLE_METRICS = [
    "mvrv",
    "sopr",
    "exchange_reserve",
    "miner_reserve",
    "realized_price",
    "cdd",
    "dormancy",
    "stablecoin_supply",
]


class OnchainAnalyzer:
    dimension_name = "onchain"

    def analyze(
        self, asset_id: str, as_of: datetime, history: list[SnapshotRow]
    ) -> DimensionReport:
        signals: list[Signal] = []
        gaps: list[str] = []
        findings: list[str] = []

        hashrate = latest_metric(history, "hash_rate")
        hr_series = metric_series(history, "hash_rate")
        if hashrate is None:
            gaps.append("hash_rate: no data")
        elif len(hr_series) >= 14:  # daily cadence -> ~2 weeks
            change = pct_change(hr_series[0], hashrate)
            if change is not None and change <= -0.10:
                signals.append(
                    Signal(
                        signal_id="onchain.hashrate_drawdown",
                        value=change,
                        points=-10,
                        label=ClaimLabel.INFERENCE,
                        rationale=f"ハッシュレートが観測窓で{change:+.1%} — "
                        "マイナー降伏の可能性（Difficulty調整と併読）",
                    )
                )
                findings.append(f"ハッシュレート{change:+.1%}低下 — 降伏パターン監視")
            else:
                signals.append(
                    Signal(
                        signal_id="onchain.hashrate_stable",
                        value=change,
                        points=0,
                        label=ClaimLabel.FACT,
                        rationale=f"ハッシュレート推移 {change:+.1%}（窓内・異常なし）"
                        if change is not None
                        else "ハッシュレート観測中",
                    )
                )
        else:
            gaps.append(f"hash_rate: history n={len(hr_series)} < 14 (trend unavailable)")

        for metric in UNAVAILABLE_METRICS:
            if latest_metric(history, metric) is None:
                gaps.append(f"{metric}: ソース未契約（IES §5の中核指標・オーナー判断待ち）")

        return compose_report(
            Dimension.ONCHAIN,
            asset_id,
            as_of,
            signals,
            gaps,
            VERSION,
            key_findings=findings,
            watch_items=["次回Difficulty調整（下方調整の連続はマイナー降伏の確認材料）"],
            invalidation="ハッシュレート系シグナルは全網ハッシュの回復（窓内プラス転換）で無効",
        )

"""Derivatives dimension (IES §6), rule-based v1.

Signals fire only with sufficient history (percentile thresholds per
IES §6.2 — never hardcoded absolute values). On thin history the report
says so via data_gaps and low conviction instead of guessing.
"""

from datetime import datetime

from bios.analysis.base import SnapshotRow, latest_metric, metric_series
from bios.analysis.models import DimensionReport, Signal, compose_report
from bios.analysis.stats import pct_change, percentile_rank
from bios.common.labels import ClaimLabel, Dimension

VERSION = "derivatives/v1"


class DerivativesAnalyzer:
    dimension_name = "derivatives"

    def analyze(
        self, asset_id: str, as_of: datetime, history: list[SnapshotRow]
    ) -> DimensionReport:
        signals: list[Signal] = []
        gaps: list[str] = []
        findings: list[str] = []
        watch: list[str] = []

        funding = latest_metric(history, "funding_rate")
        funding_hist = metric_series(history, "funding_rate")[:-1]
        if funding is None:
            gaps.append("funding_rate: no data")
        else:
            rank = percentile_rank(funding_hist, funding)
            if rank is None:
                gaps.append(
                    f"funding_rate: history n={len(funding_hist)} < 30 (percentile unavailable)"
                )
            elif rank >= 0.95:
                signals.append(
                    Signal(
                        signal_id="derivatives.funding_extreme_high",
                        value=funding,
                        points=-15,
                        label=ClaimLabel.INFERENCE,
                        rationale=f"funding {funding:+.5f} は履歴P{rank * 100:.0f} — "
                        "ロング過密（crowded_long、下方清算脆弱性）",
                    )
                )
                findings.append("Fundingが歴史的高位。ロング過密によるスクイーズ脆弱性")
                watch.append("清算カスケードの発生（funding正常化まで）")
            elif rank <= 0.05:
                signals.append(
                    Signal(
                        signal_id="derivatives.funding_extreme_low",
                        value=funding,
                        points=15,
                        label=ClaimLabel.INFERENCE,
                        rationale=f"funding {funding:+.5f} は履歴P{rank * 100:.0f} — "
                        "ショート過密（踏み上げ燃料）",
                    )
                )
                findings.append("Fundingが歴史的低位。ショートスクイーズの燃料充填")
            else:
                signals.append(
                    Signal(
                        signal_id="derivatives.funding_neutral",
                        value=funding,
                        points=0,
                        label=ClaimLabel.FACT,
                        rationale=f"funding {funding:+.5f}（履歴P{rank * 100:.0f}・中立域）",
                    )
                )

        oi = latest_metric(history, "open_interest")
        oi_series = metric_series(history, "open_interest")
        if oi is None:
            gaps.append("open_interest: no data")
        elif len(oi_series) >= 25:  # ~24h of hourly points + current
            change = pct_change(oi_series[-25], oi)
            if change is not None and abs(change) >= 0.10:
                direction = "急増" if change > 0 else "急減"
                points = -5 if change > 0 else 5  # build-up adds fragility; flush resets it
                signals.append(
                    Signal(
                        signal_id="derivatives.oi_shift_24h",
                        value=change,
                        points=points,
                        label=ClaimLabel.INFERENCE,
                        rationale=f"OIが24hで{change:+.1%}（{direction}）。急増=ポジション積上がり、急減=レバレッジリセット",
                    )
                )
                findings.append(f"OI 24h {change:+.1%} — {direction}")
        else:
            gaps.append(f"open_interest: history n={len(oi_series)} < 25 (24h change unavailable)")

        return compose_report(
            Dimension.DERIVATIVES,
            asset_id,
            as_of,
            signals,
            gaps,
            VERSION,
            key_findings=findings,
            watch_items=watch,
            invalidation="funding極値シグナルは、fundingが中立域（P25-P75）へ復帰した時点で無効",
        )

"""News / market-psychology dimension, rule-based v1.

v1 scope: Fear & Greed (already a normalized 0-100 composite, so absolute
bands are legitimate) + news-queue throughput as context. Real per-event
news analysis (14-item structure) arrives with the LLM agent runtime.
"""

from datetime import datetime
from typing import Any

from bios.analysis.base import SnapshotRow, latest_metric
from bios.analysis.models import DimensionReport, Signal, compose_report
from bios.common.labels import ClaimLabel, Dimension

VERSION = "news_flow/v1"

# (lower bound, upper bound, points, reading) — contrarian bands, small caps.
_FNG_BANDS = [
    (0, 20, 10, "極端な恐怖（歴史的に逆張り局面で出現しやすい）"),
    (20, 35, 5, "恐怖圏"),
    (35, 65, 0, "中立圏"),
    (65, 80, -5, "強欲圏"),
    (80, 101, -10, "極端な強欲（過熱の兆候）"),
]


class NewsFlowAnalyzer:
    dimension_name = "news"

    def __init__(self, queue_stats: dict[str, Any] | None = None) -> None:
        self._queue_stats = queue_stats or {}

    def analyze(
        self, asset_id: str, as_of: datetime, history: list[SnapshotRow]
    ) -> DimensionReport:
        signals: list[Signal] = []
        gaps: list[str] = []
        findings: list[str] = []

        fng = latest_metric(history, "fear_greed")
        if fng is None:
            gaps.append("fear_greed: no data")
        else:
            for low, high, points, reading in _FNG_BANDS:
                if low <= fng < high:
                    signals.append(
                        Signal(
                            signal_id="news.fear_greed_band",
                            value=fng,
                            points=points,
                            label=ClaimLabel.INFERENCE,
                            rationale=f"Fear & Greed = {fng:.0f}：{reading}。"
                            "逆張り解釈は補助シグナル（上限±10点）",
                        )
                    )
                    findings.append(f"Fear & Greed {fng:.0f}（{reading}）")
                    break

        pending = self._queue_stats.get("pending")
        if pending is not None:
            signals.append(
                Signal(
                    signal_id="news.curation_backlog",
                    value=float(pending),
                    points=0,
                    label=ClaimLabel.FACT,
                    rationale=f"未処理ニュース候補 {pending}件（イベント化はキュレーション待ち）",
                )
            )
            if pending > 50:
                findings.append(f"キュレーション滞留 {pending}件 — 人間ループの処理が必要")
        gaps.append("per-event news analysis: LLM Agentランタイム未稼働（ANTHROPIC_API_KEY待ち）")

        return compose_report(
            Dimension.NEWS,
            asset_id,
            as_of,
            signals,
            gaps,
            VERSION,
            key_findings=findings,
            invalidation="Fear&Greed帯域シグナルは帯域移動で自動的に失効（日次再計算）",
        )

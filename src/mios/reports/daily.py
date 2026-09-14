"""The daily Markdown report.

This module **formats stored artifacts and does nothing else**. It performs
no analysis, computes no score, and reaches for no series the rest of the
pipeline has not already written down. Every number it prints comes from a
row somewhere, and the row is named so a reader can go and check it.

That restriction is the point. A report that quietly computes its own
figures produces numbers nobody can reconcile with the database, and the
first time the two disagree, neither is trustworthy.

The section that matters most is "Changes From Yesterday" (指示書 §12). A
snapshot of today is a photograph; what a reader actually needs is what
moved and by how much — and because every layer here stores vintages rather
than overwriting, the difference is a subtraction rather than a guess.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from mios.analysis.repo import MacroScoreRepo
from mios.common.logutil import get_logger
from mios.config.loader import ConfigRoot
from mios.knowledge.store import CurationQueue
from mios.prediction.external import ExternalForecastRepo
from mios.prediction.repo import ForecastRepo
from mios.series.calendar import CalendarRepo
from mios.series.repo import ObservationRepo
from mios.storage.db import Database
from mios.validation.benchmark import BenchmarkReader
from mios.validation.metrics import MIN_SAMPLE, MetricsReader

logger = get_logger(__name__)

VERSION = "report/v1"

#: Series shown in the market sections, in the order a reader wants them.
RATES_BLOCK = [
    ("ser_us_treasury_2y", "US 2Y", "%"),
    ("ser_us_treasury_10y", "US 10Y", "%"),
    ("ser_us_real_yield_10y", "US 10Y real", "%"),
    ("ser_us_breakeven_10y", "US 10Y breakeven", "%"),
    ("ser_us_fed_funds_effective", "Effective fed funds", "%"),
]
JGB_BLOCK = [
    ("ser_jp_jgb_2y", "JGB 2Y", "%"),
    ("ser_jp_jgb_10y", "JGB 10Y", "%"),
    ("ser_jp_jgb_30y", "JGB 30Y", "%"),
]
FX_BLOCK = [
    ("ser_usdjpy", "USDJPY", ""),
    ("ser_usdjpy_fred", "USDJPY (FRED, tier 1)", ""),
    ("ser_us_dxy", "Broad dollar index", ""),
]
GOLD_BLOCK = [
    ("ser_xauusd", "Gold (XAU/USD)", "$"),
    ("ser_us_vix", "VIX", ""),
]


@dataclass
class Change:
    """One line of the difference between two days."""

    label: str
    yesterday: float | None
    today: float | None
    unit: str

    @property
    def delta(self) -> float | None:
        if self.yesterday is None or self.today is None:
            return None
        return self.today - self.yesterday


def _fmt(value: float | None, unit: str, places: int = 4) -> str:
    if value is None:
        return "—"
    if unit == "%":
        return f"{value:.3f}%"
    if unit == "$":
        return f"${value:,.2f}"
    return f"{value:,.{places}f}".rstrip("0").rstrip(".")


def _fmt_delta(change: Change) -> str:
    if change.delta is None:
        return "—"
    if change.unit == "%":
        # Yields move in basis points, and saying so is how a reader knows
        # whether 0.08 is a rounding artefact or a real day.
        return f"{change.delta * 100:+.1f}bp"
    return f"{change.delta:+,.4f}".rstrip("0").rstrip(".")


class DailyReport:
    def __init__(self, db: Database, config: ConfigRoot) -> None:
        self._db = db
        self._config = config
        self._observations = ObservationRepo(db)
        self._scores = MacroScoreRepo(db)
        self._forecasts = ForecastRepo(db)
        self._metrics = MetricsReader(db)
        self._external = ExternalForecastRepo(db)
        self._benchmark = BenchmarkReader(db)
        self._calendar = CalendarRepo(db)
        self._news = CurationQueue(db)

    # -------------------------------------------------------------- pieces

    def _series_value(self, series_id: str, as_of: datetime) -> tuple[float | None, date | None]:
        latest = self._observations.latest_as_of(series_id, as_of)
        if latest is None or latest.value is None:
            return None, None
        return float(latest.value), latest.observation_date

    def _market_table(
        self, block: list[tuple[str, str, str]], as_of: datetime, yesterday: datetime
    ) -> list[str]:
        lines = ["| 系列 | 前日 | 当日 | 変化 | 参照期間 |", "|---|---:|---:|---:|---|"]
        any_data = False
        for series_id, label, unit in block:
            today_value, period = self._series_value(series_id, as_of)
            past_value, _ = self._series_value(series_id, yesterday)
            if today_value is None and past_value is None:
                lines.append(f"| {label} | — | — | — | **未取得** |")
                continue
            any_data = True
            change = Change(label, past_value, today_value, unit)
            lines.append(
                f"| {label} | {_fmt(past_value, unit)} | {_fmt(today_value, unit)} | "
                f"{_fmt_delta(change)} | {period or '—'} |"
            )
        if not any_data:
            lines.append("")
            lines.append("この区分のデータはまだ1件も取得できていません。")
        return lines

    def _forecast_section(self, target_id: str, as_of: datetime) -> list[str]:
        latest = [
            row
            for row in self._forecasts.latest_per_target(as_of)
            if row["target_series_id"] == target_id
        ]
        if not latest:
            return ["予測はまだ生成されていません（`mios forecast` 未実行、または履歴不足）。"]

        lines: list[str] = []
        for row in latest:
            previous = self._forecasts.previous(
                target_id, row["target_period"], before=row["predicted_at"]
            )
            point = float(row["point_value"]) if row["point_value"] is not None else None
            baseline = float(row["baseline_value"]) if row["baseline_value"] is not None else None
            lines.append(f"**対象期間 {row['target_period']}**")
            lines.append("")
            lines.append(f"- 予測: `{point:+.4f}`（ナイーブ基準 `{baseline:+.4f}`）")
            if previous is not None and previous["point_value"] is not None:
                delta = point - float(previous["point_value"]) if point is not None else None
                lines.append(
                    f"- 前回（{previous['predicted_at'].date()}）比: `{delta:+.4f}`"
                    if delta is not None
                    else "- 前回比: —"
                )
            if row["upside_prob"] is not None:
                lines.append(
                    f"- 上振れ確率 {float(row['upside_prob']):.0%} / "
                    f"下振れ確率 {float(row['downside_prob']):.0%}（対ナイーブ基準）"
                )
            else:
                lines.append("- 確率: **算出不能**（履歴不足のため捏造せず保留）")
            lines.append(f"- 確信度: {float(row['confidence']):.2f}")
            drivers = sorted(row["drivers"], key=lambda d: -abs(d["contribution"]))[:5]
            if drivers:
                lines.append("- 主な根拠:")
                for driver in drivers:
                    lines.append(f"    - {driver['rationale']}")
            for contradiction in row["contradictions"]:
                lines.append(f"- 反対のシグナル: {contradiction}")
            for gap in row["data_gaps"]:
                lines.append(f"- 欠損: {gap}")
            lines.append("")
        return lines

    def _view_section(self, view_id: str, as_of: datetime, yesterday: datetime) -> list[str]:
        current = self._scores.latest(view_id, as_of)
        if current is None:
            return ["分析はまだ生成されていません（`mios analyze` 未実行）。"]
        previous = self._scores.previous(view_id, before=current["as_of"])

        lines = [
            f"**マクロバイアス: {float(current['score']):+.0f}（{current['stance']}）** "
            f"確信度 {float(current['confidence']):.2f}",
            "",
        ]
        if previous is not None:
            delta = float(current["score"]) - float(previous["score"])
            lines.append(
                f"前回（{previous['as_of'].date()}）から `{delta:+.0f}`"
                f"（{previous['stance']} → {current['stance']}）"
            )
            lines.append("")
        for signal in sorted(current["signals"], key=lambda s: -abs(s["points"])):
            lines.append(f"- `{signal['points']:+d}pt` {signal['rationale']}")
        for contradiction in current["contradictions"]:
            lines.append(f"- **反対方向**: {contradiction}")
        for gap in current["data_gaps"]:
            lines.append(f"- **欠損**: {gap}")
        lines.append("")
        lines.append("**この分析が構造的に見ていないもの:**")
        for blind in current["blind_spots"]:
            lines.append(f"- {blind}")
        lines.append("")
        return lines

    def _changes(self, as_of: datetime, yesterday: datetime) -> list[str]:
        """What moved since yesterday — the section a reader opens first."""
        rows: list[str] = ["| 項目 | 昨日 | 今日 | 変化 |", "|---|---:|---:|---:|"]
        found = False

        for view in self._config.analysis.views:
            current = self._scores.latest(view.view_id, as_of)
            if current is None:
                continue
            previous = self._scores.previous(view.view_id, before=current["as_of"])
            if previous is None:
                continue
            found = True
            delta = float(current["score"]) - float(previous["score"])
            rows.append(
                f"| {view.label} | {float(previous['score']):+.0f} | "
                f"{float(current['score']):+.0f} | {delta:+.0f} |"
            )

        for target in self._config.forecast.targets:
            for row in self._forecasts.latest_per_target(as_of):
                if row["target_series_id"] != target.series_id or row["point_value"] is None:
                    continue
                previous_forecast = self._forecasts.previous(
                    target.series_id, row["target_period"], before=row["predicted_at"]
                )
                if previous_forecast is None or previous_forecast["point_value"] is None:
                    continue
                found = True
                today_value = float(row["point_value"])
                past_value = float(previous_forecast["point_value"])
                rows.append(
                    f"| {target.label} 予測 ({row['target_period']}) | "
                    f"{past_value:+.4f} | {today_value:+.4f} | {today_value - past_value:+.4f} |"
                )

        for series_id, label, unit in RATES_BLOCK + JGB_BLOCK + FX_BLOCK + GOLD_BLOCK:
            current_level, _ = self._series_value(series_id, as_of)
            previous_level, _ = self._series_value(series_id, yesterday)
            if current_level is None or previous_level is None or current_level == previous_level:
                continue
            found = True
            change = Change(label, previous_level, current_level, unit)
            rows.append(
                f"| {label} | {_fmt(previous_level, unit)} | {_fmt(current_level, unit)} | "
                f"{_fmt_delta(change)} |"
            )

        if not found:
            return [
                "比較できる前日のデータがまだありません。",
                "",
                "このセクションは2日目以降から意味を持ちます"
                "（予測・分析・観測値がいずれも vintage で保存されるため、"
                "差分は推測ではなく引き算で出ます）。",
            ]
        return rows

    def _today(self, as_of: datetime) -> list[str]:
        """What is published today, and what is coming this week.

        The first question anyone asks in the morning, and the one this
        report could not answer until the calendar existed. Entries whose
        publication clock is known show a time; the rest show a day, because
        the provider gave a date and printing an hour would invent one.
        """
        start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        today = self._calendar.between(start, start + timedelta(days=1))
        week = self._calendar.between(start + timedelta(days=1), start + timedelta(days=8))

        if not today and not week:
            if not self._calendar.coverage().get("entries"):
                return [
                    "発表予定がまだ1件も取得できていません"
                    "（`mios collect --source src_fred_release_dates` → `mios calendar`）。"
                ]
            return ["今日から1週間、登録された発表予定はありません。"]

        lines: list[str] = []
        lines.append("**本日**")
        lines.append("")
        if not today:
            lines.append("- 本日の発表予定はありません。")
        else:
            lines.append("| 時刻 | 重要度 | 発表 | 対象系列 |")
            lines.append("|---|---|---|---|")
            for row in today:
                when = (
                    row["scheduled_at"].strftime("%H:%M UTC")
                    if row["time_precision"] == "exact"
                    else "**時刻未定**"
                )
                series = f"`{row['series_id']}`" if row["series_id"] else "—"
                stars = "★" * int(row["importance"])
                lines.append(f"| {when} | {stars} | {row['title']} | {series} |")
        lines.append("")
        lines.append("**今週（本日を除く）**")
        lines.append("")
        if not week:
            lines.append("- 予定はありません。")
        for row in week:
            day = row["scheduled_at"].date()
            when = (
                row["scheduled_at"].strftime("%H:%M UTC")
                if row["time_precision"] == "exact"
                else "時刻未定"
            )
            lines.append(f"- {day} {when} — {row['title']}（{'★' * int(row['importance'])}）")
        return lines

    def _headlines(self) -> list[str]:
        """Collected headlines, newest first, labelled by source tier.

        Headlines and the publisher's own summary, nothing more. No
        classification, no summarisation, no theme — none of that exists
        yet, and a section that silently presented a keyword match as
        analysis would be worse than one that presents a list.

        The tier is printed beside every item on purpose. A Tier 3 report is
        not a fact; it becomes one only when a Tier 1-2 source confirms it
        (CONSTITUTION.md Art.4), and a reader skimming a list has no other
        way to see the difference.
        """
        rows = self._news.pending(limit=25)
        if not rows:
            return ["ニュースはまだ1件も取得できていません（`mios collect` → `mios extract`）。"]
        tiers = {sid: spec.tier for sid, spec in self._config.sources.items()}
        lines: list[str] = []
        for row in rows:
            payload = row["payload"]
            title = payload.get("title") or "(no title)"
            link = payload.get("link") or ""
            tier = tiers.get(row["source_id"], payload.get("tier", 4))
            published = payload.get("published_raw") or ""
            label = f"[{title}]({link})" if link else title
            lines.append(f"- **T{tier}** {label}  \n  `{row['source_id']}` {published}")
        lines.append("")
        lines.append(
            "分類・要約・テーマ抽出は**未実装**。ここにあるのは配信元が出した"
            "見出しと要約そのままであり、MIOS による解釈は含まれない。"
        )
        return lines

    def _consensus(self, as_of: datetime) -> list[str]:
        """What the institutions say, beside what MIOS says.

        The gap between the two is the single most informative line in this
        report on any day a release is coming. Beating the naive baseline is
        routine; disagreeing with a Federal Reserve Bank's published nowcast
        is a position, and printing both forces it to be one taken
        deliberately rather than by accident.
        """
        lines: list[str] = []
        shown = 0
        for target in self._config.forecast.targets:
            mine = [
                row
                for row in self._forecasts.latest_per_target(as_of)
                if row["target_series_id"] == target.series_id
            ]
            if not mine or mine[0]["point_value"] is None:
                continue
            period = mine[0]["target_period"]
            rows = self._external.as_of(target.series_id, period, as_of)
            if not rows:
                continue
            ours = float(mine[0]["point_value"])
            shown += 1
            lines.append(f"**{target.label} {period}**")
            lines.append("")
            lines.append("| 予測者 | 予測 | MIOS との差 | 公表 | Tier |")
            lines.append("|---|---:|---:|---|---:|")
            lines.append(f"| **MIOS** | `{ours:+.4f}` {target.unit_label} | — | — | — |")
            for row in rows:
                value = float(row["point_value"])
                lines.append(
                    f"| {row['provider_id']} | `{value:+.4f}` {target.unit_label} | "
                    f"`{value - ours:+.4f}` | {row['published_at'].date()} | {row['tier']} |"
                )
            lines.append("")

        if shown == 0:
            lines.append("機関予測はまだ1件も取得できていません。")
            lines.append("")

        # Always printed, present or not: a comparison table covering two of
        # four targets reads as complete unless it says which two it is not.
        for series_id in self._config.external.uncovered:
            lines.append(
                f"- `{series_id}`: 無料で機械可読な機関予測が存在しない。"
                "比較対象はナイーブ基準のみで、ここでの skill は CPI のそれより弱い主張である。"
            )
        return lines

    def _head_to_head(self) -> list[str]:
        """The scoreboard against the institutions, on equal information."""
        rows = self._benchmark.comparisons()
        if not rows:
            return [
                "対象期間が発表され次第、機関予測も同じ初回発表値・同じナイーブ基準で採点されます。"
            ]
        lines = [
            "| 予測者 | 対象 | n | MIOS MAE | 相手 MAE | edge |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for row in rows:
            if not row.sufficient:
                lines.append(
                    f"| {row.provider_id} | {row.target_series_id} | {row.n} | "
                    f"— | — | n<{MIN_SAMPLE} のため未算出 |"
                )
                continue
            lines.append(
                f"| {row.provider_id} | {row.target_series_id} | {row.n} | "
                f"`{row.mios_mae:.5f}` | `{row.provider_mae:.5f}` | `{row.edge:+.5f}` |"
            )
        lines.append("")
        lines.append(
            "edge が正なら、同じ情報量の時点で MIOS の方が誤差が小さかったことを意味する。"
        )
        return lines

    def _data_quality(self, as_of: datetime) -> list[str]:
        coverage = {row["series_id"]: row for row in self._observations.coverage()}
        empty = sorted(
            spec.series_id
            for spec in self._config.series.series
            if int(coverage.get(spec.series_id, {}).get("vintages", 0) or 0) == 0
        )
        stale: list[str] = []
        cutoff = as_of - timedelta(days=10)
        for spec in self._config.series.series:
            row = coverage.get(spec.series_id)
            if not row or not row.get("latest_vintage"):
                continue
            if spec.frequency == "daily" and row["latest_vintage"] < cutoff:
                stale.append(f"{spec.series_id}（最終取得 {row['latest_vintage'].date()}）")

        lines = [
            f"- 登録系列: {len(self._config.series.series)}",
            f"- **データ未取得: {len(empty)} 系列**",
        ]
        if empty:
            lines.append("")
            lines.append("<details><summary>未取得の系列</summary>")
            lines.append("")
            for series_id in empty:
                lines.append(f"- `{series_id}`")
            lines.append("")
            lines.append("</details>")
        if stale:
            lines.append("")
            lines.append("**10日以上更新の止まっている日次系列:**")
            for entry in stale:
                lines.append(f"- {entry}")
        if not empty and not stale:
            lines.append("- 欠損・停止している系列はありません。")
        return lines

    def _accuracy(self) -> list[str]:
        coverage = self._metrics.coverage()
        lines = [
            f"- 採点済み予測: {coverage['scored']} 件"
            f"（{coverage['targets']} 対象 / {coverage['periods']} 期間）",
            f"- 発表待ち: {coverage['awaiting_actuals']} 件",
        ]
        if coverage["scored"] == 0:
            lines.append("")
            lines.append(
                "対象期間が発表され次第、自動的に採点されます。"
                "それまで精度について述べられることはありません。"
            )
            return lines

        reported = [row for row in self._metrics.accuracy() if row.sufficient]
        if not reported:
            lines.append("")
            lines.append(
                f"どの期間帯も {MIN_SAMPLE} 件に達していないため、精度指標は算出しません。"
                "少数の予測から出した的中率は、数字の形をした逸話です。"
            )
            return lines

        lines.append("")
        lines.append("| 対象 | 期間帯 | n | MAE | ナイーブMAE | skill | 方向的中 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for row in reported:
            direction = (
                f"{row.directional_accuracy:.0%}" if row.directional_accuracy is not None else "—"
            )
            lines.append(
                f"| {row.target_series_id} | {row.horizon} | {row.n} | "
                f"{row.mae:.5f} | {row.baseline_mae:.5f} | {row.skill:+.5f} | {direction} |"
            )
        lines.append("")
        lines.append(
            "`skill` は「ナイーブ予測の誤差 − 自分の誤差」。"
            "**正でなければ、先行指標は飾りである。**"
        )
        return lines

    # -------------------------------------------------------------- render

    def render(self, as_of: datetime) -> str:
        yesterday = as_of - timedelta(days=1)
        day = as_of.date().isoformat()
        out: list[str] = [
            f"# Daily Macro Report — {day}",
            "",
            f"> データ基準時刻 (as-of): `{as_of.isoformat()}`  ",
            f"> 生成: `{VERSION}` ／ 分析 `{self._config.analysis.method_version}`"
            f" ／ 予測 `{self._config.forecast.method_version}`",
            "",
            "本レポートは**保存済みの成果物を整形したものだけ**で構成されている。"
            "新規の計算は行っておらず、すべての数値はデータベースの行に由来する。",
            "",
        ]

        out += ["## 本日の発表 / Economic Calendar", ""]
        out += self._today(as_of)

        out += ["", "## Executive Summary", ""]
        out += self._summary(as_of)
        out += ["", "## Changes From Yesterday", ""]
        out += self._changes(as_of, yesterday)

        out += ["", "## CPI Outlook", ""]
        out += self._forecast_section("ser_us_core_cpi_index", as_of)
        out += ["### Headline CPI", ""]
        out += self._forecast_section("ser_us_cpi_index", as_of)

        out += ["", "## NFP Outlook", ""]
        out += self._forecast_section("ser_us_nfp_level", as_of)
        out += ["### Unemployment Rate", ""]
        out += self._forecast_section("ser_us_unemployment_rate", as_of)

        out += ["", "## Fed Outlook", ""]
        out += self._dimension_section("fed", as_of)
        out += ["", "## BOJ Outlook", ""]
        out += self._dimension_section("boj", as_of)

        out += ["", "## US Treasury", ""]
        out += self._market_table(RATES_BLOCK, as_of, yesterday)
        out += ["", "## Japan Government Bonds", ""]
        out += self._market_table(JGB_BLOCK, as_of, yesterday)

        out += ["", "## USDJPY", ""]
        out += self._market_table(FX_BLOCK, as_of, yesterday)
        out += [""]
        out += self._view_section("usdjpy_bias", as_of, yesterday)

        out += ["", "## Gold", ""]
        out += self._market_table(GOLD_BLOCK, as_of, yesterday)
        out += [""]
        out += self._view_section("gold_bias", as_of, yesterday)

        out += ["", "## Macro Dimensions", ""]
        out += self._dimensions_table(as_of)

        out += ["", "## Headlines", ""]
        out += self._headlines()

        out += ["", "## Consensus / Institutional Forecasts", ""]
        out += self._consensus(as_of)

        out += ["", "## Forecast Accuracy", ""]
        out += self._accuracy()

        out += ["", "### 機関予測との比較（同じ情報量の時点同士）", ""]
        out += self._head_to_head()

        out += ["", "## Data Quality / Missing Data", ""]
        out += self._data_quality(as_of)

        out += ["", "## Not Yet Implemented", ""]
        out += [
            "以下は指示書が求めているが、本レポートにはまだ存在しない。"
            "空欄ではなく欠落として明示する。",
            "",
            "- **Economic Calendar** — 発表予定の取得は未実装",
            "- **ニュースの分類・要約** — 見出しの収集は動くが、テーマ分類も"
            "要約も未実装。LLM を使う唯一の箇所になる予定で、"
            "`ANTHROPIC_API_KEY` が必要（憲法第5条：LLM は数値を作らない）",
            "- **Reuters / Bloomberg** — 公開RSSが存在しないため収集経路がない。"
            "有料APIを使わない限り取得できない",
            "- **雇用統計のコンセンサス** — NFP・失業率の月次コンセンサスは"
            "有料（Bloomberg / Reuters 調査）でしか手に入らない。"
            "この2つは機関予測と比較できず、ナイーブ基準のみが比較対象",
            "- **日本の CPI・賃金** — e-Stat の取り込みが未実装",
        ]

        out += ["", "## Sources", ""]
        out += self._sources()

        out += [
            "",
            "---",
            "",
            "*本レポートは意思決定支援であり投資助言ではない。*  ",
            "*マクロバイアスは経済環境の解釈であって価格予想ではない（CONSTITUTION.md 第10条）。*",
            "",
        ]
        return "\n".join(out) + "\n"

    def _summary(self, as_of: datetime) -> list[str]:
        """Three facts, or an honest statement that there are not three facts."""
        lines: list[str] = []
        for view in self._config.analysis.views:
            row = self._scores.latest(view.view_id, as_of)
            if row is None:
                continue
            lines.append(
                f"- **{view.label}**: {float(row['score']):+.0f}（{row['stance']}）"
                f" 確信度 {float(row['confidence']):.2f}"
            )
        for target in self._config.forecast.targets[:2]:
            for row in self._forecasts.latest_per_target(as_of):
                if row["target_series_id"] != target.series_id or row["point_value"] is None:
                    continue
                lines.append(
                    f"- **{target.label} ({row['target_period']})**: "
                    f"`{float(row['point_value']):+.4f}` "
                    f"（ナイーブ `{float(row['baseline_value']):+.4f}`）"
                )
        if not lines:
            return [
                "本日述べられることはまだない。",
                "",
                "予測・分析のいずれも生成されていないため、"
                "要約すべき成果物が存在しない。"
                "`mios collect` → `mios normalize` → `mios forecast` → `mios analyze` "
                "を実行した後、本セクションに内容が入る。",
            ]
        return lines

    def _dimension_section(self, dimension: str, as_of: datetime) -> list[str]:
        row = self._scores.latest(dimension, as_of)
        if row is None:
            return ["分析はまだ生成されていません（`mios analyze` 未実行）。"]
        previous = self._scores.previous(dimension, before=row["as_of"])
        lines = [
            f"**{float(row['score']):+.0f}（{row['stance']}）** "
            f"確信度 {float(row['confidence']):.2f}"
        ]
        if previous is not None:
            lines.append("")
            lines.append(
                f"前回（{previous['as_of'].date()}）から "
                f"`{float(row['score']) - float(previous['score']):+.0f}`"
            )
        lines.append("")
        for signal in sorted(row["signals"], key=lambda s: -abs(s["points"])):
            lines.append(f"- `{signal['points']:+d}pt` {signal['rationale']}")
        for gap in row["data_gaps"]:
            lines.append(f"- **欠損**: {gap}")
        lines.append("")
        lines.append("**見ていないもの:** " + " / ".join(row["blind_spots"]))
        return lines

    def _dimensions_table(self, as_of: datetime) -> list[str]:
        rows = {r["dimension"]: r for r in self._scores.all_latest(as_of)}
        if not rows:
            return ["分析はまだ生成されていません（`mios analyze` 未実行）。"]
        lines = [
            "| 次元 | スコア | 判定 | 確信度 | シグナル | 欠損 |",
            "|---|---:|---|---:|---:|---:|",
        ]
        for spec in self._config.analysis.dimensions:
            row = rows.get(spec.dimension)
            if row is None:
                lines.append(f"| {spec.label} | — | 未計算 | — | — | — |")
                continue
            lines.append(
                f"| {spec.label} | {float(row['score']):+.0f} | {row['stance']} | "
                f"{float(row['confidence']):.2f} | {len(row['signals'])} | "
                f"{len(row['data_gaps'])} |"
            )
        return lines

    def _sources(self) -> list[str]:
        by_tier: dict[int, list[str]] = {}
        for spec in sorted(self._config.sources.values(), key=lambda s: s.source_id):
            by_tier.setdefault(spec.tier, []).append(f"{spec.name}")
        lines: list[str] = []
        for tier in sorted(by_tier):
            lines.append(f"**Tier {tier}** — {len(by_tier[tier])} ソース")
            lines.append("")
            lines.append("<details><summary>一覧</summary>")
            lines.append("")
            for name in by_tier[tier]:
                lines.append(f"- {name}")
            lines.append("")
            lines.append("</details>")
            lines.append("")
        return lines


def write_report(db: Database, config: ConfigRoot, as_of: datetime, root: Any) -> Any:
    """Render and write ``reports/daily/YYYY-MM-DD.md``."""
    path = root / "daily" / f"{as_of.date().isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DailyReport(db, config).render(as_of), encoding="utf-8")
    logger.info("report written: %s", path)
    return path

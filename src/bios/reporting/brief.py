"""Morning Briefing v1 (IES §12.2, Report Agent principle G14):
**no new analysis here** — this module only formats stored artifacts.
Every number comes from the database; every section names its source
record. Missing artifacts render as explicit absence, never silence.
"""

from typing import Any

from bios.knowledge.timeline import TimelineEngine
from bios.storage.db import Database


class BriefingComposer:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _latest(self, table: str, asset_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            f"SELECT * FROM {table} WHERE asset_id=%(a)s ORDER BY as_of DESC LIMIT 1",
            {"a": asset_id},
        )

    def compose(self, asset_id: str, asset_name: str) -> str:
        decision = self._latest("decisions", asset_id)
        card = self._latest("score_cards", asset_id)
        scenario_set = self._latest("scenario_sets", asset_id)
        snapshot = self._db.query_one(
            "SELECT * FROM market_snapshots WHERE asset_id=%(a)s ORDER BY ts DESC LIMIT 1",
            {"a": asset_id},
        )
        recent_events = self._db.query(
            """
            SELECT event_id, type, title, magnitude_initial FROM events
            WHERE status='confirmed' AND known_at > now() - interval '48 hours'
              AND curation->>'by' = 'human'
            ORDER BY magnitude_initial DESC NULLS LAST LIMIT 10
            """
        )
        pending = self._db.query_one(
            "SELECT count(*) AS n FROM curation_queue WHERE status='pending'"
        )
        chains = TimelineEngine(self._db)  # noqa: F841 - reserved for chain expansion
        active_chains = self._db.query(
            "SELECT chain_id, title, watch_points FROM event_chains WHERE status='active'"
        )
        degraded = self._db.query(
            "SELECT source_id FROM sources WHERE enabled=false AND kind <> 'seed'"
        )

        lines: list[str] = [f"━━━ BIOS Morning Briefing ── {asset_name} ━━━", ""]

        if decision:
            inv = decision["invalidation"]
            lines += [
                f"■ 今日の判断: {decision['action']}（確信度 {decision['conviction']:.2f}）",
                f"  {decision['delta_from_yesterday'] or '（初回判断）'}",
                f"  根拠: {decision['rationale']}",
                f"  反対意見: {decision['counter_argument']}",
                f"  無効化条件: {inv.get('condition')}（チェック: {inv.get('check')}）",
                f"  リスク: {decision['risk_note']}",
                f"  [decision: {decision['decision_id']}]",
                "",
            ]
        else:
            lines += ["■ 今日の判断: 未生成（`bios decide` 未実行）", ""]

        if card:
            phase = card["phase"]
            lines += [
                f"■ 市場フェーズ: trend={phase.get('trend')} vol={phase.get('vol')} "
                f"liquidity={phase.get('liquidity')}（weight set: {phase.get('key')}）",
                f"■ 総合スコア: {card['composite']:+d}（{card['verdict_hint']}）"
                f" 対立指数={card['conflict_index']:.2f}"
                f" データ完全性={card['data_completeness']:.2f}",
            ]
            for entry in card["dimensions"]:
                gaps = f" gaps={len(entry['data_gaps'])}" if entry["data_gaps"] else ""
                lines.append(
                    f"  ├ {entry['dimension']:<12} score={entry['score']:+4d}"
                    f" 寄与={entry['contribution']:+6.1f}{gaps}"
                )
            lines += [
                f"  [score card: {card['score_card_id']} / weights {card['weights_version']}]",
                "",
            ]

        if snapshot:
            metrics = snapshot["asset_metrics"]
            lines += [
                f"■ 市況 FACT（{snapshot['ts'].isoformat()}）: "
                f"価格 ${float(snapshot['price_usd'] or 0):,.0f} / "
                f"Funding {metrics.get('funding_rate', 'N/A')} / "
                f"F&G {metrics.get('fear_greed', 'N/A')}",
                "",
            ]

        if scenario_set:
            lines.append("■ シナリオ（確率は基準率なしのINFERENCE — 下記注記）")
            for s in scenario_set["scenarios"]:
                lines.append(f"  ├ {s['name']}: {s['probability']:.0%} — {s['rationale']}")
                lines.append(f"  │   先行指標: {' / '.join(s['leading_indicators'])}")
            lines += [f"  注記: {scenario_set['base_rate_note']}", ""]

        lines.append("■ 直近48hの承認済みイベント" + ("" if recent_events else ": なし"))
        for event in recent_events:
            magnitude = event["magnitude_initial"] or "-"
            lines.append(f"  ├ [M{magnitude}] {event['title']}（{event['type']}）")
        lines.append("")

        lines.append("■ 進行中チェーンの監視点")
        for chain in active_chains:
            for wp in chain["watch_points"]:
                lines.append(f"  ├ {chain['chain_id']}: {wp}")
        lines.append("")

        n_pending = pending["n"] if pending else 0
        lines.append(f"■ キュレーション待ち: {n_pending}件（`bios curate list`）")
        if degraded:
            names = ", ".join(d["source_id"] for d in degraded)
            lines.append(f"■ データ欠損の明示: 無効化中ソース = {names}")
        lines += [
            "",
            "※ 本ブリーフィングは保存済み成果物の整形のみ（新規分析なし・数値は全てDB由来）",
            "※ BIOSは意思決定支援であり投資助言ではない（憲法第7条）",
        ]
        return "\n".join(lines)

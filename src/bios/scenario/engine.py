"""Scenario Engine v1 (IES §12.3 shape, rule-based probabilities).

Constitution Art.5 forbids fabricated statistics. With the historical
base-rate DB still thin (n<5 analog sets), v1 probabilities are an
**explicit uninformative prior (1/3 each) plus a bounded, documented tilt
from the composite score** — a deterministic formula, labeled INFERENCE,
with the base-rate absence stated on the record. The LLM/base-rate
upgrade replaces the formula, not the schema.
"""

import json
from datetime import datetime
from typing import Any

from bios.common.ids import IdKind, make_dated_id
from bios.common.schema import BiosModel
from bios.scoring.composite import ScoreCard
from bios.storage.db import Database

VERSION = "scenario/v1"
MAX_TILT = 0.15  # composite ±100 shifts bull/bear prob by at most ±0.15

BASE_RATE_NOTE = (
    "歴史事例DB構築中（類似事例n<5）のため基準率は算出不能。"
    "確率は無情報事前分布(1/3)±スコア傾き（最大±0.15・式はscenario/v1）であり統計ではない。"
)


class Scenario(BiosModel):
    name: str
    direction: str  # bull | neutral | bear
    probability: float
    rationale: str
    rationale_refs: list[str]
    leading_indicators: list[str]
    invalidation: str
    label: str = "INFERENCE"


class ScenarioSet(BiosModel):
    scenario_set_id: str
    asset_id: str
    as_of: datetime
    scenarios: list[Scenario]
    method_version: str = VERSION
    base_rate_note: str = BASE_RATE_NOTE


def _top_signal_ids(card: ScoreCard, positive: bool) -> list[str]:
    refs: list[str] = []
    for entry in card.dimensions:
        for signal in entry.top_signals:
            points = int(signal.get("points", 0))
            if (points > 0) == positive and points != 0:
                refs.append(str(signal.get("signal_id")))
    return refs[:5]


def build_scenario_set(card: ScoreCard, asset_slug: str) -> ScenarioSet:
    tilt = round(card.composite / 100 * MAX_TILT, 4)
    p_bull = 1 / 3 + tilt
    p_bear = 1 / 3 - tilt
    p_neutral = 1 - p_bull - p_bear
    probs = [round(p, 3) for p in (p_bull, p_neutral, p_bear)]
    probs[1] = round(1.0 - probs[0] - probs[2], 3)  # force exact sum 1.0

    bull_refs = _top_signal_ids(card, positive=True)
    bear_refs = _top_signal_ids(card, positive=False)
    scenarios = [
        Scenario(
            name="続伸",
            direction="bull",
            probability=probs[0],
            rationale=f"強気寄与シグナル（{', '.join(bull_refs) or 'なし'}）＋事前分布",
            rationale_refs=bull_refs,
            leading_indicators=["ETF/現物フローのプラス転換", "funding中立のまま価格切り上げ"],
            invalidation="弱気側次元スコアの合計が強気側を2日連続で上回る",
        ),
        Scenario(
            name="レンジ",
            direction="neutral",
            probability=probs[1],
            rationale="方向シグナルの不足（データ完全性・対立指数を反映）",
            rationale_refs=[],
            leading_indicators=["実現ボラ低下", "OI横ばい"],
            invalidation="composite絶対値が40超へ拡大",
        ),
        Scenario(
            name="調整",
            direction="bear",
            probability=probs[2],
            rationale=f"弱気寄与シグナル（{', '.join(bear_refs) or 'なし'}）＋事前分布",
            rationale_refs=bear_refs,
            leading_indicators=["取引所入金増加", "funding過熱＋価格上昇鈍化"],
            invalidation="強気側次元スコアの合計が弱気側を2日連続で上回る",
        ),
    ]
    total = round(sum(s.probability for s in scenarios), 6)
    if total != 1.0:  # schema-level guarantee (IES: Σp=1.0)
        raise ValueError(f"scenario probabilities must sum to 1.0, got {total}")
    return ScenarioSet(
        scenario_set_id=make_dated_id(
            IdKind.SCENARIO_SET, card.as_of.date().isoformat(), asset_slug
        ),
        asset_id=card.asset_id,
        as_of=card.as_of,
        scenarios=scenarios,
    )


class ScenarioRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, scenario_set: ScenarioSet) -> bool:
        if self._db.query_one(
            "SELECT 1 AS x FROM scenario_sets WHERE scenario_set_id=%(i)s",
            {"i": scenario_set.scenario_set_id},
        ):
            return False
        data = scenario_set.model_dump(mode="json")
        data["scenarios"] = json.dumps(data["scenarios"], ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO scenario_sets (scenario_set_id, asset_id, as_of, scenarios,
                method_version, base_rate_note)
            VALUES (%(scenario_set_id)s, %(asset_id)s, %(as_of)s, %(scenarios)s,
                %(method_version)s, %(base_rate_note)s)
            """,
            data,
        )
        return True

    def get(self, scenario_set_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM scenario_sets WHERE scenario_set_id=%(i)s", {"i": scenario_set_id}
        )

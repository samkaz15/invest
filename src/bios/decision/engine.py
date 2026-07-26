"""Decision Engine v1 (Constitution Art.5/7, IES §11.5 + MSD G13 rules).

Deterministic rules, WAIT-biased by design:
* BUY only on strong composite AND sufficient data completeness,
* TAKE_PROFIT requires a tracked position (none in v1 — flat assumed),
* conflict caps conviction; thin data forces WAIT,
* no decision leaves without an invalidation (DB schema enforces too).
"""

import json
from typing import Any

from bios.common.ids import IdKind, make_dated_id
from bios.common.labels import Action
from bios.common.schema import BiosModel
from bios.scenario.engine import ScenarioSet
from bios.scoring.composite import ScoreCard
from bios.storage.db import Database

VERSION = "decision/v1"
MIN_COMPLETENESS_FOR_ACTION = 0.6
BUY_THRESHOLD = 40
CONFLICT_CAP_THRESHOLD = 0.6
CONFLICT_CONVICTION_CAP = 0.55


class Decision(BiosModel):
    decision_id: str
    asset_id: str
    as_of: Any  # datetime; kept loose for pydantic json dump symmetry
    action: Action
    conviction: float
    rationale: str
    rationale_refs: list[str]
    counter_argument: str
    invalidation: dict[str, str]
    risk_note: str
    delta_from_yesterday: str
    score_card_id: str
    scenario_set_id: str
    engine_version: str = VERSION


def _counter_argument(card: ScoreCard, action: Action) -> str:
    """Critic-lite: the strongest signal opposing the taken stance."""
    opposing: list[tuple[int, str]] = []
    for entry in card.dimensions:
        for signal in entry.top_signals:
            points = int(signal.get("points", 0))
            if action is Action.BUY and points < 0:
                opposing.append((points, str(signal.get("rationale"))))
            elif action in (Action.WAIT, Action.TAKE_PROFIT) and points > 0:
                opposing.append((-points, str(signal.get("rationale"))))
    if not opposing:
        return "明確な反対材料は検出されず。ただしデータ欠損自体が最大の反対材料である。"
    opposing.sort()
    return f"最強の反論: {opposing[0][1]}"


def decide(
    card: ScoreCard,
    scenario_set: ScenarioSet,
    asset_slug: str,
    previous: dict[str, Any] | None,
) -> Decision:
    reasons: list[str] = []
    if card.data_completeness < MIN_COMPLETENESS_FOR_ACTION:
        action = Action.WAIT
        reasons.append(
            f"データ完全性 {card.data_completeness:.2f} < {MIN_COMPLETENESS_FOR_ACTION}"
            "（証拠不十分時のデフォルトはWAIT）"
        )
    elif card.composite >= BUY_THRESHOLD:
        action = Action.BUY
        reasons.append(f"composite {card.composite:+d} ≥ +{BUY_THRESHOLD} かつデータ充足")
    else:
        action = Action.WAIT
        reasons.append(
            f"composite {card.composite:+d} はBUY閾値未満"
            "（TAKE_PROFITはポジション追跡未実装のため対象外）"
        )

    conviction = round(min(0.9, 0.3 + 0.4 * card.data_completeness + abs(card.composite) / 500), 2)
    if card.conflict_index > CONFLICT_CAP_THRESHOLD:
        conviction = min(conviction, CONFLICT_CONVICTION_CAP)
        reasons.append(
            f"対立指数 {card.conflict_index:.2f} > {CONFLICT_CAP_THRESHOLD}: 確信度を制限"
        )

    refs = [s["signal_id"] for e in card.dimensions for s in e.top_signals if s.get("points")]
    delta = ""
    if previous:
        prev_action = previous["action"]
        delta = (
            f"昨日: {prev_action} → 本日: {action.value}（変化なし）"
            if prev_action == action.value
            else f"昨日: {prev_action} → 本日: {action.value}（理由: {reasons[0]}）"
        )

    bear = next(s for s in scenario_set.scenarios if s.direction == "bear")
    return Decision(
        decision_id=make_dated_id(IdKind.DECISION, card.as_of.date().isoformat(), asset_slug),
        asset_id=card.asset_id,
        as_of=card.as_of,
        action=action,
        conviction=conviction,
        rationale="；".join(reasons),
        rationale_refs=refs[:10],
        counter_argument=_counter_argument(card, action),
        invalidation={
            "condition": bear.invalidation
            if action is Action.BUY
            else "composite が +40 を超えデータ完全性0.6以上（WAIT解除条件）",
            "check": "daily",
        },
        risk_note=(
            f"最悪シナリオ: 「{bear.name}」(p={bear.probability:.0%})。"
            "確率は基準率なしのINFERENCE（scenario_set参照）"
        ),
        delta_from_yesterday=delta,
        score_card_id=card.score_card_id,
        scenario_set_id=scenario_set.scenario_set_id,
    )


class DecisionJournal:
    def __init__(self, db: Database) -> None:
        self._db = db

    def latest(self, asset_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM decisions WHERE asset_id=%(a)s ORDER BY as_of DESC LIMIT 1",
            {"a": asset_id},
        )

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM decisions WHERE decision_id=%(i)s", {"i": decision_id}
        )

    def save(self, decision: Decision) -> bool:
        """Append-only: one decision per (asset, day)."""
        if self.get(decision.decision_id):
            return False
        data = decision.model_dump(mode="json")
        data["rationale_refs"] = json.dumps(data["rationale_refs"], ensure_ascii=False)
        data["invalidation"] = json.dumps(data["invalidation"], ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO decisions (decision_id, asset_id, as_of, action, conviction, rationale,
                rationale_refs, counter_argument, invalidation, risk_note, delta_from_yesterday,
                score_card_id, scenario_set_id, engine_version)
            VALUES (%(decision_id)s, %(asset_id)s, %(as_of)s, %(action)s, %(conviction)s,
                %(rationale)s, %(rationale_refs)s, %(counter_argument)s, %(invalidation)s,
                %(risk_note)s, %(delta_from_yesterday)s, %(score_card_id)s, %(scenario_set_id)s,
                %(engine_version)s)
            """,
            data,
        )
        return True

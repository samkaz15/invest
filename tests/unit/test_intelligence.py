"""Scoring / scenario / decision / outcome rule tests (pure logic)."""

from datetime import UTC, datetime, timedelta

import pytest

from bios.common.labels import Action
from bios.config.models import ScoringConfig
from bios.decision.engine import decide
from bios.decision.outcomes import verdict_for
from bios.scenario.engine import build_scenario_set
from bios.scoring.composite import build_score_card
from bios.scoring.composite import verdict_for as score_verdict
from bios.scoring.regime import Regime, classify

AS_OF = datetime(2026, 7, 17, 6, 0, tzinfo=UTC)
SCORING = ScoringConfig(
    weights_version="w_test",
    weight_sets={"default": {"derivatives": 1.0, "onchain": 1.0, "news": 1.0}},
)


def _report(dimension: str, score: int, conviction: float = 0.8, points: int | None = None) -> dict:
    signals = []
    if points is not None:
        signals = [
            {
                "signal_id": f"{dimension}.sig",
                "points": points,
                "rationale": f"{dimension} signal",
                "value": 1.0,
                "label": "INFERENCE",
                "evidence_refs": [],
            }
        ]
    return {
        "dimension": dimension,
        "score": score,
        "conviction": conviction,
        "signals": signals,
        "data_gaps": [],
    }


def _card(scores: dict[str, int], conviction: float = 0.8):
    reports = [_report(d, s, conviction, points=s) for d, s in scores.items()]
    return build_score_card("ent_asset_btc", "btc", AS_OF, reports, SCORING, Regime())


# ---------------------------------------------------------------- scoring


def test_composite_is_weighted_mean_and_verdict_maps() -> None:
    card = _card({"derivatives": 60, "onchain": 30, "news": 0})
    assert card.composite == 30
    assert card.verdict_hint == "BULLISH"
    assert score_verdict(50) == "STRONG_BULLISH" and score_verdict(-50) == "STRONG_BEARISH"
    assert card.score_card_id == "sc_2026-07-17_btc"


def test_conflict_index_flags_split_dimensions() -> None:
    unanimous = _card({"derivatives": 40, "onchain": 40, "news": 40})
    assert unanimous.conflict_index == 0.0
    split = _card({"derivatives": 50, "onchain": -50, "news": 0})
    assert split.conflict_index == 1.0  # opinionated dimensions fully split


def test_regime_unknown_on_thin_history() -> None:
    regime = classify([{"ts": AS_OF, "price_usd": 60000.0, "asset_metrics": {}}])
    assert regime.trend == "unknown" and regime.phase_key() == "default"


def test_regime_bull_on_uptrend() -> None:
    history = [
        {"ts": AS_OF - timedelta(days=30 - i), "price_usd": 50000.0 + i * 500, "asset_metrics": {}}
        for i in range(30)
    ]
    assert classify(history).trend == "bull"


# --------------------------------------------------------------- scenario


def test_scenario_probabilities_sum_to_one_and_tilt_with_score() -> None:
    bullish = build_scenario_set(_card({"derivatives": 80, "onchain": 80, "news": 80}), "btc")
    probs = {s.direction: s.probability for s in bullish.scenarios}
    assert round(sum(probs.values()), 6) == 1.0
    assert probs["bull"] > probs["bear"]
    assert all(s.label == "INFERENCE" for s in bullish.scenarios)
    assert "統計ではない" in bullish.base_rate_note  # honesty on the record


# --------------------------------------------------------------- decision


def test_thin_data_forces_wait() -> None:
    card = _card({"derivatives": 90, "onchain": 90, "news": 90}, conviction=0.2)
    decision = decide(card, build_scenario_set(card, "btc"), "btc", previous=None)
    assert decision.action is Action.WAIT
    assert "データ完全性" in decision.rationale
    assert decision.invalidation["condition"]  # never empty


def test_strong_composite_with_data_buys_and_carries_critic() -> None:
    card = _card({"derivatives": 60, "onchain": 60, "news": 60}, conviction=0.8)
    decision = decide(card, build_scenario_set(card, "btc"), "btc", previous={"action": "WAIT"})
    assert decision.action is Action.BUY
    assert decision.counter_argument  # critic-lite always present
    assert "WAIT → 本日: BUY" in decision.delta_from_yesterday


def test_conflict_caps_conviction() -> None:
    card = _card({"derivatives": 100, "onchain": -80, "news": 60}, conviction=0.9)
    assert card.conflict_index > 0.6
    decision = decide(card, build_scenario_set(card, "btc"), "btc", previous=None)
    assert decision.conviction <= 0.55


# ---------------------------------------------------------------- outcome


@pytest.mark.parametrize(
    ("action", "ret", "expected"),
    [
        ("BUY", 0.05, "correct"),
        ("BUY", -0.05, "incorrect"),
        ("BUY", 0.0, "neutral"),
        ("WAIT", -0.10, "correct"),  # avoided a drop
        ("WAIT", 0.10, "incorrect"),  # opportunity cost is scored as a loss
        ("WAIT", 0.01, "neutral"),
        ("TAKE_PROFIT", -0.05, "correct"),
        ("TAKE_PROFIT", 0.05, "incorrect"),
    ],
)
def test_outcome_verdicts(action: str, ret: float, expected: str) -> None:
    assert verdict_for(action, ret) == expected

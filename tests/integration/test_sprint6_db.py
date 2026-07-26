"""Integration tests: virtual portfolio, backtest, alerts, why-explainer,
against the real test database."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bios.common.labels import Action
from bios.config.loader import load_config
from bios.decision.alerts import AlertEngine
from bios.decision.backtest import BacktestEngine
from bios.decision.engine import Decision, DecisionJournal
from bios.decision.portfolio import VirtualPortfolio
from bios.knowledge.snapshots import SnapshotRepo
from bios.reporting.why import WhyExplainer
from bios.scenario.engine import ScenarioRepo, build_scenario_set
from bios.scoring.composite import ScoreCardRepo, build_score_card
from bios.scoring.regime import Regime
from bios.storage.db import Database
from bios.storage.migrate import MigrationRunner
from bios.storage.sync import sync_sources
from tests.integration.test_storage import TEST_DSN

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 8, 1, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def db() -> Database:
    database = Database(TEST_DSN)
    if not database.ping():
        pytest.skip(f"test database unreachable: {TEST_DSN}")
    database.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    MigrationRunner(database, REPO / "db" / "migrations").apply_all()
    sync_sources(database, load_config(REPO / "config").sources)
    return database


def _report(dimension: str, score: int, points: int) -> dict:
    return {
        "dimension": dimension,
        "score": score,
        "conviction": 0.8,
        "signals": [
            {
                "signal_id": f"{dimension}.sig",
                "points": points,
                "rationale": "r",
                "value": 1.0,
                "label": "INFERENCE",
                "evidence_refs": [],
            }
        ],
        "data_gaps": [],
    }


def _make_decision(
    db: Database, as_of: datetime, action_bias: int, position_units: float
) -> Decision:
    from bios.decision.engine import decide

    scoring = load_config(REPO / "config").scoring
    reports = [
        _report("derivatives", action_bias, action_bias),
        _report("onchain", action_bias, action_bias),
        _report("news", action_bias, action_bias),
    ]
    card = build_score_card("ent_asset_btc", "btc", as_of, reports, scoring, Regime())
    ScoreCardRepo(db).save(card)
    scenario_set = build_scenario_set(card, "btc")
    ScenarioRepo(db).save(scenario_set)
    decision = decide(card, scenario_set, "btc", previous=None, position_units=position_units)
    DecisionJournal(db).save(decision)
    return decision


def test_take_profit_only_fires_with_open_position(db: Database) -> None:
    from bios.decision.engine import decide

    scoring = load_config(REPO / "config").scoring
    bearish = [
        _report("derivatives", -60, -60),
        _report("onchain", -60, -60),
        _report("news", -60, -60),
    ]
    card = build_score_card("ent_asset_btc", "btc", T0, bearish, scoring, Regime())
    scenario_set = build_scenario_set(card, "btc")
    flat = decide(card, scenario_set, "btc", previous=None, position_units=0.0)
    assert flat.action is Action.WAIT  # bearish but flat -> nothing to sell
    held = decide(card, scenario_set, "btc", previous=None, position_units=1.0)
    assert held.action is Action.TAKE_PROFIT


def test_virtual_portfolio_and_backtest_roundtrip(db: Database) -> None:
    snapshots = SnapshotRepo(db)
    snapshots.upsert("ent_asset_btc", T0, 100.0, None, {})
    snapshots.upsert("ent_asset_btc", T0 + timedelta(days=1), 200.0, None, {})

    buy_decision = _make_decision(db, T0, action_bias=60, position_units=0.0)
    assert buy_decision.action is Action.BUY
    portfolio = VirtualPortfolio(db)
    portfolio.apply(buy_decision.decision_id, "ent_asset_btc", Action.BUY, T0, 100.0)
    assert float(portfolio.position("ent_asset_btc")["units"]) == 1.0

    tp_decision = _make_decision(db, T0 + timedelta(days=1), action_bias=-60, position_units=1.0)
    assert tp_decision.action is Action.TAKE_PROFIT
    portfolio.apply(
        tp_decision.decision_id,
        "ent_asset_btc",
        Action.TAKE_PROFIT,
        T0 + timedelta(days=1),
        200.0,
    )
    assert float(portfolio.position("ent_asset_btc")["units"]) == 0.0

    report = BacktestEngine(db).run("ent_asset_btc")
    assert report.n_trades == 1
    assert report.strategy_return == pytest.approx(1.0)  # 100 -> 200
    assert report.buy_hold_return == pytest.approx(1.0)  # same window, same move
    assert report.excess_vs_buy_hold == pytest.approx(0.0)


def test_alert_engine_fires_on_extreme_signal_and_disabled_source(db: Database) -> None:
    _make_decision(db, T0 + timedelta(days=2), action_bias=90, position_units=0.0)
    db.execute("UPDATE sources SET enabled=false WHERE source_id='src_fred_dgs10'")
    alerts = AlertEngine(db).scan("ent_asset_btc")
    categories = {a.category for a in alerts}
    assert "signal" in categories
    assert "data_gap" in categories
    stored = AlertEngine(db).recent("ent_asset_btc")
    assert len(stored) == len(alerts)


def test_why_explainer_traces_decision_to_signals(db: Database) -> None:
    decision = _make_decision(db, T0 + timedelta(days=3), action_bias=45, position_units=0.0)
    output = WhyExplainer(db).explain(decision.decision_id)
    assert decision.decision_id in output
    assert "derivatives.sig" in output
    assert WhyExplainer(db).explain("dcs_nonexistent").startswith("decision")

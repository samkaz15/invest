"""Backtest metrics: pure math over synthetic trade lists."""

import pytest

from bios.decision.backtest import _closed_trade_returns, _max_drawdown


def _trade(action: str, price: float, ts: int) -> dict:
    return {"action": action, "price_usd": price, "ts": ts}


def test_pairs_buy_then_take_profit_in_order() -> None:
    trades = [
        _trade("BUY", 100, 1),
        _trade("TAKE_PROFIT", 110, 2),  # +10%
        _trade("BUY", 200, 3),
        _trade("TAKE_PROFIT", 180, 4),  # -10%
        _trade("BUY", 50, 5),  # still open -> excluded
    ]
    returns = _closed_trade_returns(trades)
    assert returns == pytest.approx([0.1, -0.1])


def test_unordered_input_is_sorted_by_ts() -> None:
    trades = [_trade("TAKE_PROFIT", 110, 2), _trade("BUY", 100, 1)]
    assert _closed_trade_returns(trades) == pytest.approx([0.1])


def test_max_drawdown_from_equity_curve() -> None:
    assert _max_drawdown([1.0, 1.2, 0.9, 1.1]) == pytest.approx(-0.25)
    assert _max_drawdown([1.0]) is None

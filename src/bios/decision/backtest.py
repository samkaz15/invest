"""Backtest metrics (IES §13.4): win rate, expectancy, profit factor,
Sharpe, max drawdown — all measured against the **virtual portfolio's**
trade history, and always reported alongside Buy&Hold over the same
window. A decision engine that cannot beat B&H has no value (IES §14.4).
"""

import statistics
from typing import Any

from bios.common.schema import BiosModel
from bios.storage.db import Database

TRADING_DAYS_PER_YEAR = 365  # crypto trades every day


class BacktestReport(BiosModel):
    asset_id: str
    n_trades: int
    win_rate: float | None
    expectancy: float | None
    profit_factor: float | None
    sharpe: float | None
    max_drawdown: float | None
    strategy_return: float | None
    buy_hold_return: float | None
    excess_vs_buy_hold: float | None
    note: str = ""


def _closed_trade_returns(trades: list[dict[str, Any]]) -> list[float]:
    """Pair BUY-then-TAKE_PROFIT rows in chronological order into round-trip
    returns. Unmatched trailing BUYs (still open) are excluded — you cannot
    score a trade that hasn't closed."""
    returns: list[float] = []
    open_price: float | None = None
    for trade in sorted(trades, key=lambda t: t["ts"]):
        if trade["action"] == "BUY" and open_price is None:
            open_price = float(trade["price_usd"])
        elif trade["action"] == "TAKE_PROFIT" and open_price is not None:
            returns.append(float(trade["price_usd"]) / open_price - 1)
            open_price = None
    return returns


def _max_drawdown(equity_curve: list[float]) -> float | None:
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


class BacktestEngine:
    def __init__(self, db: Database) -> None:
        self._db = db

    def run(self, asset_id: str) -> BacktestReport:
        trades = self._db.query(
            "SELECT * FROM virtual_trades WHERE asset_id=%(a)s ORDER BY ts", {"a": asset_id}
        )
        returns = _closed_trade_returns(trades)
        n = len(returns)
        if n == 0:
            return BacktestReport(
                asset_id=asset_id,
                n_trades=0,
                win_rate=None,
                expectancy=None,
                profit_factor=None,
                sharpe=None,
                max_drawdown=None,
                strategy_return=None,
                buy_hold_return=None,
                excess_vs_buy_hold=None,
                note="決済済みトレードなし（判断がBUY→TAKE_PROFITと確定するまで採点不能）",
            )

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        win_rate = len(wins) / n
        gross_profit = sum(wins)
        gross_loss = -sum(losses)
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
        expectancy = statistics.fmean(returns)
        sharpe = None
        if n >= 2 and statistics.pstdev(returns) > 0:
            sharpe = statistics.fmean(returns) / statistics.pstdev(returns) * (n**0.5)

        equity = [1.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r))
        strategy_return = equity[-1] - 1
        mdd = _max_drawdown(equity)

        prices = self._db.query(
            "SELECT price_usd FROM market_snapshots WHERE asset_id=%(a)s "
            "AND price_usd IS NOT NULL ORDER BY ts",
            {"a": asset_id},
        )
        bh_return = None
        if len(prices) >= 2:
            bh_return = float(prices[-1]["price_usd"]) / float(prices[0]["price_usd"]) - 1

        return BacktestReport(
            asset_id=asset_id,
            n_trades=n,
            win_rate=round(win_rate, 3),
            expectancy=round(expectancy, 4),
            profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
            sharpe=round(sharpe, 2) if sharpe is not None else None,
            max_drawdown=round(mdd, 4) if mdd is not None else None,
            strategy_return=round(strategy_return, 4),
            buy_hold_return=round(bh_return, 4) if bh_return is not None else None,
            excess_vs_buy_hold=(
                round(strategy_return - bh_return, 4) if bh_return is not None else None
            ),
        )

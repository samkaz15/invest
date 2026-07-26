"""Virtual portfolio (IES §13.3): mechanically translate Decisions into a
paper position so performance can be scored against Buy&Hold.

Rules: BUY adds one unit at the day's execution price (briefing snapshot,
06:00 cadence approximated by "price at as_of"); TAKE_PROFIT closes the
whole position; WAIT is a no-op. This is deliberately the simplest
faithful mechanism — anything fancier (sizing, leverage) is out of scope
for a decision-support system (Constitution Art.7).
"""

from datetime import datetime
from typing import Any

from bios.common.labels import Action
from bios.storage.db import Database

UNIT_SIZE = 1.0


class VirtualPortfolio:
    def __init__(self, db: Database) -> None:
        self._db = db

    def position(self, asset_id: str) -> dict[str, Any]:
        row = self._db.query_one(
            "SELECT * FROM virtual_positions WHERE asset_id=%(a)s", {"a": asset_id}
        )
        return row or {"asset_id": asset_id, "units": 0.0, "avg_price_usd": None}

    def apply(
        self, decision_id: str, asset_id: str, action: Action, ts: datetime, price_usd: float
    ) -> str:
        """Apply one decision's effect; returns what happened (for logging)."""
        pos = self.position(asset_id)
        units = float(pos["units"])
        if action is Action.BUY:
            new_units = units + UNIT_SIZE
            old_avg = float(pos["avg_price_usd"]) if pos["avg_price_usd"] else 0.0
            new_avg = (old_avg * units + price_usd * UNIT_SIZE) / new_units
            self._upsert(asset_id, new_units, new_avg)
            self._record_trade(decision_id, asset_id, ts, "BUY", price_usd, UNIT_SIZE)
            return f"opened/added {UNIT_SIZE} unit @ {price_usd}"
        if action is Action.TAKE_PROFIT and units > 0:
            self._upsert(asset_id, 0.0, None)
            self._record_trade(decision_id, asset_id, ts, "TAKE_PROFIT", price_usd, units)
            return f"closed {units} units @ {price_usd}"
        return "no-op (WAIT or no position to close)"

    def _upsert(self, asset_id: str, units: float, avg_price: float | None) -> None:
        self._db.execute(
            """
            INSERT INTO virtual_positions (asset_id, units, avg_price_usd)
            VALUES (%(a)s, %(u)s, %(p)s)
            ON CONFLICT (asset_id) DO UPDATE SET
                units=EXCLUDED.units, avg_price_usd=EXCLUDED.avg_price_usd, updated_at=now()
            """,
            {"a": asset_id, "u": units, "p": avg_price},
        )

    def _record_trade(
        self, decision_id: str, asset_id: str, ts: datetime, action: str, price: float, units: float
    ) -> None:
        self._db.execute(
            """
            INSERT INTO virtual_trades (decision_id, asset_id, ts, action, price_usd, units)
            VALUES (%(d)s, %(a)s, %(ts)s, %(act)s, %(p)s, %(u)s)
            ON CONFLICT (decision_id) DO NOTHING
            """,
            {"d": decision_id, "a": asset_id, "ts": ts, "act": action, "p": price, "u": units},
        )

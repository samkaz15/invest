"""Learning loop v1 (IES §13.3): score past decisions against what the
market actually did at +1d/+7d/+30d/+90d.

Scoring rules v1 (thresholds documented, changes need ADR per §13.8):
* BUY  — correct if return > +2%, incorrect if < -2%, else neutral.
* WAIT — correct if return < -5% (avoided a drop), incorrect if > +5%
         (opportunity cost is a real loss — a system that always waits
         must not score well), else neutral.
* TAKE_PROFIT — correct if return < -2% after exit, incorrect if > +2%.
"""

from datetime import timedelta
from typing import Any

from bios.common.logutil import get_logger
from bios.storage.db import Database

logger = get_logger(__name__)

VERSION = "outcomes/v1"
HORIZONS = {
    "+1d": timedelta(days=1),
    "+7d": timedelta(days=7),
    "+30d": timedelta(days=30),
    "+90d": timedelta(days=90),
}
ACTION_BAND = 0.02
WAIT_BAND = 0.05


def verdict_for(action: str, ret: float) -> str:
    if action == "BUY":
        return (
            "correct" if ret > ACTION_BAND else ("incorrect" if ret < -ACTION_BAND else "neutral")
        )
    if action == "TAKE_PROFIT":
        return (
            "correct" if ret < -ACTION_BAND else ("incorrect" if ret > ACTION_BAND else "neutral")
        )
    # WAIT
    return "correct" if ret < -WAIT_BAND else ("incorrect" if ret > WAIT_BAND else "neutral")


class OutcomeScorer:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _price_at(self, asset_id: str, ts: Any, tolerance: timedelta) -> dict[str, Any] | None:
        return self._db.query_one(
            """
            SELECT ts, price_usd FROM market_snapshots
            WHERE asset_id=%(a)s AND ts >= %(ts)s AND ts <= %(lim)s AND price_usd IS NOT NULL
            ORDER BY ts LIMIT 1
            """,
            {"a": asset_id, "ts": ts, "lim": ts + tolerance},
        )

    def run(self) -> dict[str, int]:
        scored = 0
        decisions = self._db.query("SELECT * FROM decisions ORDER BY as_of")
        for decision in decisions:
            base = self._price_at(decision["asset_id"], decision["as_of"], timedelta(hours=6))
            if base is None:
                continue
            done = {
                r["horizon"]
                for r in self._db.query(
                    "SELECT horizon FROM decision_outcomes WHERE decision_id=%(i)s",
                    {"i": decision["decision_id"]},
                )
            }
            for horizon, delta in HORIZONS.items():
                if horizon in done:
                    continue
                target = self._price_at(
                    decision["asset_id"], decision["as_of"] + delta, timedelta(hours=24)
                )
                if target is None:
                    continue
                ret = float(target["price_usd"]) / float(base["price_usd"]) - 1
                self._db.execute(
                    """
                    INSERT INTO decision_outcomes (decision_id, horizon, return, verdict)
                    VALUES (%(i)s, %(h)s, %(r)s, %(v)s)
                    ON CONFLICT DO NOTHING
                    """,
                    {
                        "i": decision["decision_id"],
                        "h": horizon,
                        "r": ret,
                        "v": verdict_for(decision["action"], ret),
                    },
                )
                scored += 1
        logger.info("outcomes scored: %d", scored)
        return {"scored": scored}

    def summary(self) -> list[dict[str, Any]]:
        return self._db.query(
            """
            SELECT d.action, o.horizon,
                   count(*) AS n,
                   sum((o.verdict='correct')::int) AS correct,
                   sum((o.verdict='incorrect')::int) AS incorrect,
                   round(avg(o.return)::numeric, 4) AS avg_return
            FROM decision_outcomes o JOIN decisions d ON d.decision_id=o.decision_id
            GROUP BY d.action, o.horizon ORDER BY d.action, o.horizon
            """
        )

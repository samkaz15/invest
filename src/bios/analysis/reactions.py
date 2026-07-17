"""Market Reaction batch (MSD §11): stamp +1h/+1d/+7d/+30d/+90d returns
onto events, computed from stored snapshots.

Base price = first snapshot at/after the event's known_at (the market
could not trade on it earlier — look-ahead discipline). A horizon is
computed only when a snapshot exists within its tolerance window; missing
horizons simply wait for future runs (the batch is idempotent).
"""

from datetime import datetime, timedelta
from typing import Any

from bios.analysis.repo import AnalysisRepo
from bios.common.logutil import get_logger
from bios.storage.db import Database

logger = get_logger(__name__)

HORIZONS: dict[str, timedelta] = {
    "+1h": timedelta(hours=1),
    "+1d": timedelta(days=1),
    "+7d": timedelta(days=7),
    "+30d": timedelta(days=30),
    "+90d": timedelta(days=90),
}
# Snapshot must land within this slack after the ideal timestamp.
TOLERANCE: dict[str, timedelta] = {
    "+1h": timedelta(hours=2),
    "+1d": timedelta(hours=6),
    "+7d": timedelta(hours=24),
    "+30d": timedelta(hours=48),
    "+90d": timedelta(hours=72),
}


class ReactionBatch:
    def __init__(self, db: Database, repo: AnalysisRepo) -> None:
        self._db = db
        self._repo = repo

    def _snapshot_at_or_after(
        self, asset_id: str, ts: datetime, tolerance: timedelta
    ) -> dict[str, Any] | None:
        return self._db.query_one(
            """
            SELECT ts, price_usd FROM market_snapshots
            WHERE asset_id=%(a)s AND ts >= %(ts)s AND ts <= %(limit)s
              AND price_usd IS NOT NULL
            ORDER BY ts LIMIT 1
            """,
            {"a": asset_id, "ts": ts, "limit": ts + tolerance},
        )

    def run(self, asset_id: str) -> dict[str, int]:
        events = self._db.query(
            """
            SELECT event_id, known_at FROM events
            WHERE status='confirmed' AND assets @> %(asset)s
            """,
            {"asset": f'[{{"asset_id": "{asset_id}"}}]'},
        )
        computed = skipped = 0
        for event in events:
            base = self._snapshot_at_or_after(asset_id, event["known_at"], TOLERANCE["+1h"])
            if base is None:
                skipped += 1
                continue
            for horizon, delta in HORIZONS.items():
                target = self._snapshot_at_or_after(
                    asset_id, event["known_at"] + delta, TOLERANCE[horizon]
                )
                if target is None or target["ts"] <= base["ts"]:
                    continue
                self._repo.save_reaction(
                    event["event_id"],
                    asset_id,
                    horizon,
                    base["ts"],
                    float(base["price_usd"]),
                    target["ts"],
                    float(target["price_usd"]),
                )
                computed += 1
        logger.info("reactions %s: computed=%d events_without_base=%d", asset_id, computed, skipped)
        return {"computed": computed, "events_without_base": skipped}

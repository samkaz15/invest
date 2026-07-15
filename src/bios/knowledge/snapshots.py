"""Market snapshot repository (MSD §11). Asset-agnostic: common columns +
asset_metrics JSONB declared per asset in config/assets/*.yaml."""

import json
from datetime import datetime
from typing import Any

from bios.storage.db import Database


class SnapshotRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(
        self,
        asset_id: str,
        ts: datetime,
        price_usd: float | None,
        volume_24h_usd: float | None,
        asset_metrics: dict[str, Any],
        macro_context: dict[str, Any] | None = None,
        sources: dict[str, str] | None = None,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO market_snapshots (asset_id, ts, price_usd, volume_24h_usd,
                asset_metrics, macro_context, sources)
            VALUES (%(a)s, %(ts)s, %(p)s, %(v)s, %(m)s, %(mc)s, %(src)s)
            ON CONFLICT (asset_id, ts) DO UPDATE SET
                price_usd=EXCLUDED.price_usd, volume_24h_usd=EXCLUDED.volume_24h_usd,
                asset_metrics=market_snapshots.asset_metrics || EXCLUDED.asset_metrics,
                macro_context=market_snapshots.macro_context || EXCLUDED.macro_context,
                sources=market_snapshots.sources || EXCLUDED.sources
            """,
            {
                "a": asset_id,
                "ts": ts,
                "p": price_usd,
                "v": volume_24h_usd,
                "m": json.dumps(asset_metrics, ensure_ascii=False),
                "mc": json.dumps(macro_context or {}, ensure_ascii=False),
                "src": json.dumps(sources or {}, ensure_ascii=False),
            },
        )

    def latest(self, asset_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM market_snapshots WHERE asset_id=%(a)s ORDER BY ts DESC LIMIT 1",
            {"a": asset_id},
        )

    def range(self, asset_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT * FROM market_snapshots WHERE asset_id=%(a)s AND ts >= %(s)s "
            "AND ts < %(e)s ORDER BY ts",
            {"a": asset_id, "s": start, "e": end},
        )

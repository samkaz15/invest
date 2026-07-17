"""Persistence for analysis outputs (derived data — recomputable)."""

import json
from datetime import datetime
from typing import Any

from bios.analysis.models import DimensionReport
from bios.storage.db import Database


class AnalysisRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save_report(self, report: DimensionReport) -> None:
        data = report.model_dump(mode="json")
        for key in ("signals", "key_findings", "watch_items", "data_gaps"):
            data[key] = json.dumps(data[key], ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO dimension_reports (asset_id, dimension, as_of, score, conviction,
                signals, key_findings, watch_items, data_gaps, invalidation, analyzer_version)
            VALUES (%(asset_id)s, %(dimension)s, %(as_of)s, %(score)s, %(conviction)s,
                %(signals)s, %(key_findings)s, %(watch_items)s, %(data_gaps)s,
                %(invalidation)s, %(analyzer_version)s)
            ON CONFLICT (asset_id, dimension, as_of) DO UPDATE SET
                score=EXCLUDED.score, conviction=EXCLUDED.conviction,
                signals=EXCLUDED.signals, key_findings=EXCLUDED.key_findings,
                watch_items=EXCLUDED.watch_items, data_gaps=EXCLUDED.data_gaps,
                invalidation=EXCLUDED.invalidation, analyzer_version=EXCLUDED.analyzer_version
            """,
            data,
        )

    def latest_reports(self, asset_id: str) -> list[dict[str, Any]]:
        return self._db.query(
            """
            SELECT DISTINCT ON (dimension) * FROM dimension_reports
            WHERE asset_id=%(a)s ORDER BY dimension, as_of DESC
            """,
            {"a": asset_id},
        )

    def save_reaction(
        self,
        event_id: str,
        asset_id: str,
        horizon: str,
        base_ts: datetime,
        base_price: float,
        target_ts: datetime,
        target_price: float,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO market_reactions (event_id, asset_id, horizon, base_ts, base_price,
                target_ts, target_price, return)
            VALUES (%(e)s, %(a)s, %(h)s, %(bts)s, %(bp)s, %(tts)s, %(tp)s, %(r)s)
            ON CONFLICT (event_id, asset_id, horizon) DO UPDATE SET
                base_ts=EXCLUDED.base_ts, base_price=EXCLUDED.base_price,
                target_ts=EXCLUDED.target_ts, target_price=EXCLUDED.target_price,
                return=EXCLUDED.return, computed_at=now()
            """,
            {
                "e": event_id,
                "a": asset_id,
                "h": horizon,
                "bts": base_ts,
                "bp": base_price,
                "tts": target_ts,
                "tp": target_price,
                "r": target_price / base_price - 1,
            },
        )

    def reactions_for(self, event_id: str) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT * FROM market_reactions WHERE event_id=%(e)s ORDER BY horizon",
            {"e": event_id},
        )

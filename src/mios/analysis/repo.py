"""Persistence for macro scores.

Append-only, unlike the BIOS analysis repository this replaces. That one
upserted on (asset, dimension, as_of), so a recomputation silently
overwrote what the system had thought and "what did the analysis say on the
5th?" had no answer (docs/REPOSITORY_AUDIT.md §14 L3).
"""

import json
from datetime import datetime
from typing import Any

from mios.analysis.macro import MacroScore
from mios.common.logutil import get_logger
from mios.storage.db import Database

logger = get_logger(__name__)


class MacroScoreRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, score: MacroScore) -> bool:
        """Store a score. Returns False if this as-of already has one."""
        payload = {
            "score_id": score.score_id,
            "dimension": score.dimension,
            "as_of": score.as_of,
            "score": score.score,
            "stance": score.stance,
            "confidence": score.confidence,
            "signals": json.dumps(
                [s.model_dump(mode="json") for s in score.signals], ensure_ascii=False
            ),
            "contradictions": json.dumps(score.contradictions, ensure_ascii=False),
            "data_gaps": json.dumps(score.data_gaps, ensure_ascii=False),
            "blind_spots": json.dumps(score.blind_spots, ensure_ascii=False),
            "method_version": score.method_version,
        }
        with self._db.transaction() as conn:
            row = conn.execute(
                """
                INSERT INTO macro_scores (score_id, dimension, as_of, score, stance,
                    confidence, signals, contradictions, data_gaps, blind_spots,
                    method_version)
                VALUES (%(score_id)s, %(dimension)s, %(as_of)s, %(score)s, %(stance)s,
                    %(confidence)s, %(signals)s, %(contradictions)s, %(data_gaps)s,
                    %(blind_spots)s, %(method_version)s)
                ON CONFLICT (score_id) DO NOTHING
                RETURNING score_id
                """,
                payload,
            ).fetchone()
        return row is not None

    def latest(self, dimension: str, as_of: datetime) -> dict[str, Any] | None:
        """The newest score for a dimension that existed at ``as_of``."""
        return self._db.query_one(
            """
            SELECT * FROM macro_scores
            WHERE dimension = %(d)s AND as_of <= %(a)s
            ORDER BY as_of DESC LIMIT 1
            """,
            {"d": dimension, "a": as_of},
        )

    def all_latest(self, as_of: datetime) -> list[dict[str, Any]]:
        return self._db.query(
            """
            SELECT DISTINCT ON (dimension) * FROM macro_scores
            WHERE as_of <= %(a)s ORDER BY dimension, as_of DESC
            """,
            {"a": as_of},
        )

    def previous(self, dimension: str, before: datetime) -> dict[str, Any] | None:
        """The score that stood before ``before`` — the "yesterday" column of
        a daily report (指示書 §12)."""
        return self._db.query_one(
            """
            SELECT * FROM macro_scores
            WHERE dimension = %(d)s AND as_of < %(b)s
            ORDER BY as_of DESC LIMIT 1
            """,
            {"d": dimension, "b": before},
        )

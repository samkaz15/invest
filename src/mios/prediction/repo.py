"""Storing forecasts, once each, forever.

The only write is an insert that declines to overwrite. That is not
defensive coding — it is the requirement: the value of this table comes
entirely from being able to ask, months later, what MIOS thought ten days
before a release, and a single overwrite anywhere destroys that answer for
that target (CONSTITUTION.md Art.6-4).

The database backs it up with an append-only trigger, so even a direct
psql session cannot rewrite a past opinion.
"""

import json
from datetime import date, datetime
from typing import Any

from mios.common.logutil import get_logger
from mios.prediction.models import Forecast
from mios.storage.db import Database

logger = get_logger(__name__)


class ForecastRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, forecast: Forecast) -> bool:
        """Store a forecast. Returns False if today's already exists.

        Re-running the daily job must be safe, so a same-day repeat is a
        no-op rather than an error — but it is also never an update. If the
        inputs changed during the day, that opinion belongs to tomorrow.
        """
        data = forecast.model_dump(mode="json")
        for key in ("drivers", "contradictions", "data_gaps"):
            data[key] = json.dumps(data[key], ensure_ascii=False)
        with self._db.transaction() as conn:
            row = conn.execute(
                """
                INSERT INTO predictions (forecast_id, target_series_id, target_period,
                    predicted_at, as_of, point_value, baseline_value, upside_prob,
                    downside_prob, confidence, method_version, drivers, contradictions,
                    data_gaps)
                VALUES (%(forecast_id)s, %(target_series_id)s, %(target_period)s,
                    %(predicted_at)s, %(as_of)s, %(point_value)s, %(baseline_value)s,
                    %(upside_prob)s, %(downside_prob)s, %(confidence)s, %(method_version)s,
                    %(drivers)s, %(contradictions)s, %(data_gaps)s)
                ON CONFLICT (forecast_id) DO NOTHING
                RETURNING forecast_id
                """,
                data,
            ).fetchone()
        if row is None:
            logger.info("%s already recorded; left untouched", forecast.forecast_id)
            return False
        return True

    def get(self, forecast_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM predictions WHERE forecast_id=%(i)s", {"i": forecast_id}
        )

    def vintages(self, target_series_id: str, target_period: date) -> list[dict[str, Any]]:
        """Every forecast ever made for one period, oldest first.

        This is the table's reason to exist: it answers "what did we think,
        and when did we change our mind?", and lets accuracy be measured
        against how far out the call was made.
        """
        return self._db.query(
            """
            SELECT * FROM predictions
            WHERE target_series_id = %(s)s AND target_period = %(p)s
            ORDER BY predicted_at
            """,
            {"s": target_series_id, "p": target_period},
        )

    def latest_per_target(self, as_of: datetime) -> list[dict[str, Any]]:
        """The newest forecast for each target that existed at ``as_of``.

        As-of filtered like every other read: a report dated in the past
        must show the forecast that stood then, not the one that stands now.
        """
        return self._db.query(
            """
            SELECT DISTINCT ON (target_series_id, target_period) *
            FROM predictions WHERE predicted_at <= %(as_of)s
            ORDER BY target_series_id, target_period, predicted_at DESC
            """,
            {"as_of": as_of},
        )

    def all_with_scores(self) -> list[dict[str, Any]]:
        """Every forecast ever made, with its score where one exists.

        Deliberately unfiltered and deliberately here. This is a present-time
        export of accumulated evidence rather than a historical replay, so it
        takes no as-of — but it still lives in the repository, because the
        rule is that nothing else writes SQL against `predictions` at all.
        A reader allowed to make an exception is a reader that will.
        """
        return self._db.query(
            """
            SELECT p.*, e.actual, e.error, e.skill, e.direction_hit
            FROM predictions p
            LEFT JOIN forecast_errors e USING (forecast_id)
            ORDER BY p.target_series_id, p.target_period, p.predicted_at
            """
        )

    def previous(
        self, target_series_id: str, target_period: date, before: datetime
    ) -> dict[str, Any] | None:
        """The forecast that stood before ``before`` — the "yesterday" of a
        daily report's change column (指示書 §12)."""
        return self._db.query_one(
            """
            SELECT * FROM predictions
            WHERE target_series_id = %(s)s AND target_period = %(p)s
              AND predicted_at < %(b)s
            ORDER BY predicted_at DESC LIMIT 1
            """,
            {"s": target_series_id, "p": target_period, "b": before},
        )

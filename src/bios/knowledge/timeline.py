"""Timeline Engine (MSD §9): ordered views over the Event Store.

The load-bearing rule: **as-of queries filter on known_at**, never
occurred_at — reproducing "what BIOS could have known on date X" is the
foundation of backtesting (look-ahead bias exclusion).
"""

from datetime import datetime
from typing import Any

from bios.storage.db import Database


class TimelineEngine:
    def __init__(self, db: Database) -> None:
        self._db = db

    def events_between(
        self,
        start: datetime,
        end: datetime,
        chain_id: str | None = None,
        entity_id: str | None = None,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Events that became known in [start, end), ordered by known_at.
        ``as_of`` additionally hides anything learned after that instant."""
        sql = """
            SELECT DISTINCT e.* FROM events e
            LEFT JOIN event_participations p ON p.event_id = e.event_id
            WHERE e.known_at >= %(start)s AND e.known_at < %(end)s
              AND e.status <> 'retracted'
        """
        params: dict[str, Any] = {"start": start, "end": end}
        if as_of is not None:
            # known_at is the epistemic filter (what the market could know).
            # recorded_at is provenance only — filtering on it would hide
            # seeded historical events recorded long after they happened.
            sql += " AND e.known_at <= %(as_of)s"
            params["as_of"] = as_of
        if chain_id is not None:
            sql += " AND e.chain_id = %(chain)s"
            params["chain"] = chain_id
        if entity_id is not None:
            sql += " AND p.entity_id = %(entity)s"
            params["entity"] = entity_id
        sql += " ORDER BY known_at"
        return self._db.query(sql, params)

    def chain_events(self, chain_id: str) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT * FROM events WHERE chain_id=%(c)s AND status <> 'retracted' "
            "ORDER BY occurred_at",
            {"c": chain_id},
        )

    def ongoing_events(self) -> list[dict[str, Any]]:
        """Events still in progress (ended_at is NULL and flagged continuing)."""
        return self._db.query(
            "SELECT * FROM events WHERE ended_at IS NULL AND status='confirmed' "
            "AND chain_id IN (SELECT chain_id FROM event_chains WHERE status='active') "
            "ORDER BY known_at DESC"
        )

    def latest_resolution(self, event_id: str) -> dict[str, Any] | None:
        """Follow the supersedes chain to the newest version of an event."""
        return self._db.query_one(
            """
            WITH RECURSIVE tip AS (
                SELECT * FROM events WHERE event_id = %(e)s
                UNION ALL
                SELECT e.* FROM events e JOIN tip ON e.supersedes = tip.event_id
            )
            SELECT * FROM tip ORDER BY recorded_at DESC LIMIT 1
            """,
            {"e": event_id},
        )

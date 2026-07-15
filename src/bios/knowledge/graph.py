"""Entity master and relation queries (Knowledge Graph read/maintenance)."""

import json
from typing import Any

from bios.common.logutil import get_logger
from bios.knowledge.models import ChainRecord, EntityRecord
from bios.storage.db import Database

logger = get_logger(__name__)


class EntityRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, entity: EntityRecord) -> None:
        data = entity.model_dump(mode="json")
        for key in ("aliases", "identifiers", "attributes"):
            data[key] = json.dumps(data[key], ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO entities (entity_id, kind, name, aliases, identifiers, attributes,
                confidence)
            VALUES (%(entity_id)s, %(kind)s, %(name)s, %(aliases)s, %(identifiers)s,
                %(attributes)s, %(confidence)s)
            ON CONFLICT (entity_id) DO UPDATE SET
                name=EXCLUDED.name, aliases=EXCLUDED.aliases,
                identifiers=EXCLUDED.identifiers, attributes=EXCLUDED.attributes,
                updated_at=now()
            """,
            data,
        )

    def get(self, entity_id: str) -> dict[str, Any] | None:
        return self._db.query_one("SELECT * FROM entities WHERE entity_id=%(e)s", {"e": entity_id})

    def find_by_name(self, text: str) -> list[dict[str, Any]]:
        """Exact name or alias match (deterministic first pass of resolution)."""
        return self._db.query(
            "SELECT * FROM entities WHERE lower(name)=lower(%(t)s) "
            "OR aliases @> to_jsonb(ARRAY[%(t)s])",
            {"t": text},
        )


class ChainRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, chain: ChainRecord) -> None:
        data = chain.model_dump(mode="json")
        for key in ("milestones", "watch_points"):
            data[key] = json.dumps(data[key], ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO event_chains (chain_id, title, chain_type, parent_chain_id, status,
                started_at, closed_at, milestones, watch_points, summary)
            VALUES (%(chain_id)s, %(title)s, %(chain_type)s, %(parent_chain_id)s, %(status)s,
                %(started_at)s, %(closed_at)s, %(milestones)s, %(watch_points)s, %(summary)s)
            ON CONFLICT (chain_id) DO UPDATE SET
                title=EXCLUDED.title, status=EXCLUDED.status, closed_at=EXCLUDED.closed_at,
                milestones=EXCLUDED.milestones, watch_points=EXCLUDED.watch_points,
                summary=EXCLUDED.summary, updated_at=now()
            """,
            data,
        )

    def active(self) -> list[dict[str, Any]]:
        return self._db.query("SELECT * FROM event_chains WHERE status='active' ORDER BY chain_id")

    def get(self, chain_id: str) -> dict[str, Any] | None:
        return self._db.query_one(
            "SELECT * FROM event_chains WHERE chain_id=%(c)s", {"c": chain_id}
        )

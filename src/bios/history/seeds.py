"""Historical DB seed loader (MSD §10.2): seeds/chains/*.yaml -> Event Store.

Idempotent: existing events are skipped, chains/entities are upserted.
Seed evidence quality is the owner's Phase 1 curation duty; the loader
only enforces structure (every event carries at least one evidence).
"""

from pathlib import Path
from typing import Any

import yaml

from bios.common.errors import ConfigError
from bios.common.logutil import get_logger
from bios.knowledge.graph import ChainRepo, EntityRepo
from bios.knowledge.models import (
    ChainRecord,
    EntityRecord,
    EventRecord,
    EvidenceRecord,
    Participation,
    RelationRecord,
)
from bios.knowledge.store import EventStore
from bios.storage.db import Database

logger = get_logger(__name__)


class SeedLoader:
    def __init__(
        self, db: Database, events: EventStore, entities: EntityRepo, chains: ChainRepo
    ) -> None:
        self._db = db
        self._events = events
        self._entities = entities
        self._chains = chains

    def load_dir(self, seeds_dir: Path) -> dict[str, int]:
        counts = {"chains": 0, "entities": 0, "events": 0, "skipped": 0}
        for path in sorted(seeds_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ConfigError(f"seed {path} must be a mapping")
            self._load_one(data, counts, origin=path.name)
        logger.info("seeds loaded: %s", counts)
        return counts

    def _load_one(self, data: dict[str, Any], counts: dict[str, int], origin: str) -> None:
        for src in data.get("sources", []):
            self._db.execute(
                """
                INSERT INTO sources (source_id, name, kind, tier, enabled, notes)
                VALUES (%(source_id)s, %(name)s, 'seed', %(tier)s, false, %(notes)s)
                ON CONFLICT (source_id) DO NOTHING
                """,
                {"notes": "", **src},
            )
        for ent in data.get("entities", []):
            self._entities.upsert(EntityRecord.model_validate(ent))
            counts["entities"] += 1
        chain_id: str | None = None
        if "chain" in data:
            chain = ChainRecord.model_validate(data["chain"])
            self._chains.upsert(chain)
            chain_id = chain.chain_id
            counts["chains"] += 1
        for raw_event in data.get("events", []):
            spec = dict(raw_event)
            evidences = [EvidenceRecord.model_validate(e) for e in spec.pop("evidence", [])]
            participations = [
                Participation.model_validate(p) for p in spec.pop("participations", [])
            ]
            relations = [
                RelationRecord.model_validate({"created_by": f"seed:{origin}", **r})
                for r in spec.pop("relations", [])
            ]
            spec.setdefault("chain_id", chain_id)
            spec.setdefault("curation", {"by": "seed", "origin": origin})
            event = EventRecord.model_validate(spec)
            if self._events.exists(event.event_id):
                counts["skipped"] += 1
                continue
            self._events.insert_event(event, evidences, participations, relations)
            counts["events"] += 1

"""Event Store and curation queue — the write side of L3.

Invariants enforced here, inside one transaction per event:
* an event without at least one evidence cannot be written (Art.4),
* participations must reference existing entities,
* event type must exist in the taxonomy,
* corrections insert a superseding row, never mutate (DB trigger backs this).
"""

import json
from typing import Any

from bios.common.errors import BiosError
from bios.common.ids import IdKind, new_id
from bios.common.logutil import get_logger
from bios.common.timeutil import utc_now
from bios.config.models import EventTaxonomy
from bios.knowledge.models import EventRecord, EvidenceRecord, Participation, RelationRecord
from bios.storage.db import Database

logger = get_logger(__name__)


class IntegrityError(BiosError):
    """A write violated an Event Store invariant."""


class EventStore:
    def __init__(self, db: Database, taxonomy: EventTaxonomy) -> None:
        self._db = db
        self._taxonomy = taxonomy

    def exists(self, event_id: str) -> bool:
        return (
            self._db.query_one("SELECT 1 AS x FROM events WHERE event_id=%(e)s", {"e": event_id})
            is not None
        )

    def insert_event(
        self,
        event: EventRecord,
        evidences: list[EvidenceRecord],
        participations: list[Participation] | None = None,
        relations: list[RelationRecord] | None = None,
    ) -> None:
        participations = participations or []
        relations = relations or []
        if not evidences:
            raise IntegrityError(f"{event.event_id}: an event needs at least one evidence")
        if event.type not in self._taxonomy.types:
            raise IntegrityError(f"{event.event_id}: unknown event type {event.type!r}")
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO events (event_id, schema_version, status, supersedes, type, title,
                    summary_fact, occurred_at, known_at, ended_at, time_precision, chain_id,
                    confidence, magnitude_initial, assets, tags, curation)
                VALUES (%(event_id)s, %(schema_version)s, %(status)s, %(supersedes)s, %(type)s,
                    %(title)s, %(summary_fact)s, %(occurred_at)s, %(known_at)s, %(ended_at)s,
                    %(time_precision)s, %(chain_id)s, %(confidence)s, %(magnitude_initial)s,
                    %(assets)s, %(tags)s, %(curation)s)
                """,
                _jsonify(event.model_dump(mode="json"), ["assets", "tags", "curation"]),
            )
            for ev in evidences:
                conn.execute(
                    """
                    INSERT INTO evidences (evidence_id, raw_item_id, source_id, tier, url,
                        archived_url, quote, published_at, retrieved_at)
                    VALUES (%(evidence_id)s, %(raw_item_id)s, %(source_id)s, %(tier)s, %(url)s,
                        %(archived_url)s, %(quote)s, %(published_at)s, %(retrieved_at)s)
                    ON CONFLICT (evidence_id) DO NOTHING
                    """,
                    ev.model_dump(mode="json"),
                )
                conn.execute(
                    "INSERT INTO event_evidences (event_id, evidence_id) VALUES (%(e)s, %(v)s)",
                    {"e": event.event_id, "v": ev.evidence_id},
                )
            for p in participations:
                conn.execute(
                    """
                    INSERT INTO event_participations (event_id, entity_id, role, detail)
                    VALUES (%(e)s, %(ent)s, %(role)s, %(detail)s)
                    """,
                    {"e": event.event_id, "ent": p.entity_id, "role": p.role, "detail": p.detail},
                )
            for rel in relations:
                conn.execute(
                    """
                    INSERT INTO event_relations (from_event, to_event, rel_type, confidence,
                        evidence_id, created_by)
                    VALUES (%(from_event)s, %(to_event)s, %(rel_type)s, %(confidence)s,
                        %(evidence_id)s, %(created_by)s)
                    """,
                    rel.model_dump(mode="json"),
                )
        logger.info("event stored: %s (%s)", event.event_id, event.type)

    def get(self, event_id: str) -> dict[str, Any] | None:
        return self._db.query_one("SELECT * FROM events WHERE event_id=%(e)s", {"e": event_id})


class CurationQueue:
    """Candidates awaiting the human loop (MSD §3.3-3)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def enqueue(self, source_id: str, payload: dict[str, Any], dedupe_key: str) -> bool:
        """Queue a candidate; returns False if the same item is already known."""
        with self._db.transaction() as conn:
            row = conn.execute(
                """
                INSERT INTO curation_queue (candidate_id, source_id, payload, dedupe_key)
                VALUES (%(id)s, %(s)s, %(p)s, %(k)s)
                ON CONFLICT (dedupe_key) DO NOTHING
                RETURNING candidate_id
                """,
                {
                    "id": new_id(IdKind.EVIDENCE).replace("evd_", "cand_", 1),
                    "s": source_id,
                    "p": json.dumps(payload, ensure_ascii=False),
                    "k": dedupe_key,
                },
            ).fetchone()
            return row is not None

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT * FROM curation_queue WHERE status='pending' ORDER BY created_at LIMIT %(n)s",
            {"n": limit},
        )

    def resolve(
        self, candidate_id: str, status: str, event_id: str | None = None, note: str = ""
    ) -> None:
        if status not in ("approved", "rejected"):
            raise IntegrityError(f"invalid curation resolution {status!r}")
        self._db.execute(
            "UPDATE curation_queue SET status=%(st)s, reviewed_at=%(now)s, "
            "review_note=%(note)s, event_id=%(ev)s WHERE candidate_id=%(c)s",
            {"st": status, "now": utc_now(), "note": note, "ev": event_id, "c": candidate_id},
        )


def _jsonify(data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    for key in keys:
        data[key] = json.dumps(data[key], ensure_ascii=False)
    return data

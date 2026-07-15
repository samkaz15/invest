"""Sync config-file masters into their DB mirrors (YAML is the truth,
the DB copy exists for FK integrity and joins — MSD §13)."""

from bios.config.models import SourceSpec
from bios.storage.db import Database


def sync_sources(db: Database, sources: dict[str, SourceSpec]) -> int:
    with db.transaction() as conn:
        for spec in sources.values():
            conn.execute(
                """
                INSERT INTO sources (source_id, name, kind, tier, enabled, notes)
                VALUES (%(source_id)s, %(name)s, %(kind)s, %(tier)s, %(enabled)s, %(notes)s)
                ON CONFLICT (source_id) DO UPDATE SET
                    name=EXCLUDED.name, kind=EXCLUDED.kind, tier=EXCLUDED.tier,
                    enabled=EXCLUDED.enabled, notes=EXCLUDED.notes, synced_at=now()
                """,
                spec.model_dump(),
            )
    return len(sources)

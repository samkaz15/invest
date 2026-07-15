"""News extraction, rule-based first pass (L2).

Feed-entry raw items become curation-queue candidates. No LLM here yet:
the LLM extractor (Agent sprint) will replace `payload -> candidate`
enrichment, while queueing/dedup/bookkeeping stay as they are.
Dedup at this stage is by article link (the raw store already deduped
identical payloads; the queue dedupes re-published URLs).
"""

import hashlib
import json
from typing import Any

from bios.common.logutil import get_logger
from bios.config.models import SourceSpec
from bios.ingestion.adapters.rss import CONTENT_TYPE as FEED_CONTENT_TYPE
from bios.ingestion.rawstore import RawStore
from bios.knowledge.store import CurationQueue
from bios.storage.db import Database

logger = get_logger(__name__)


class NewsExtractor:
    def __init__(
        self, db: Database, store: RawStore, queue: CurationQueue, sources: dict[str, SourceSpec]
    ) -> None:
        self._db = db
        self._store = store
        self._queue = queue
        self._sources = sources

    def _processed(self) -> set[str]:
        return {
            r["raw_item_id"] for r in self._db.query("SELECT raw_item_id FROM extraction_state")
        }

    def _mark(self, raw_item_id: str) -> None:
        self._db.execute(
            "INSERT INTO extraction_state (raw_item_id) VALUES (%(r)s) ON CONFLICT DO NOTHING",
            {"r": raw_item_id},
        )

    def run(self) -> dict[str, int]:
        """Process all unprocessed feed-entry raw items into candidates."""
        done = self._processed()
        queued = skipped = 0
        for source_id, spec in self._sources.items():
            if spec.kind != "rss":
                continue
            for item in self._store.items(source_id):
                if item.raw_item_id in done:
                    continue
                if item.content_type != FEED_CONTENT_TYPE:
                    self._mark(item.raw_item_id)
                    continue
                entry: dict[str, Any] = json.loads(item.payload_text)
                candidate = {
                    "kind": "news",
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "published_raw": entry.get("published"),
                    "summary": entry.get("summary"),
                    "source_id": source_id,
                    "tier": spec.tier,
                    "raw_item_id": item.raw_item_id,
                    "retrieved_at": item.retrieved_at.isoformat(),
                }
                key = hashlib.sha256(
                    (entry.get("link") or entry.get("guid") or item.content_hash).encode()
                ).hexdigest()
                if self._queue.enqueue(source_id, candidate, dedupe_key=key):
                    queued += 1
                else:
                    skipped += 1
                self._mark(item.raw_item_id)
        logger.info("news extraction: queued=%d duplicate=%d", queued, skipped)
        return {"queued": queued, "duplicate": skipped}

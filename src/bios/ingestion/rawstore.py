"""Raw store: permanent, append-only, hash-deduplicated.

Sprint 2 ships the file implementation; the PostgreSQL ``raw_items`` table
(MSD §13) plugs in behind the same protocol in the storage sprint. Layout:

    <root>/<source_id>/<YYYY-MM>/<raw_item_id>.json
    <root>/<source_id>/_hashes.txt        # dedup ledger, one hash per line
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from bios.common.errors import BiosError
from bios.ingestion.rawitem import RawItem


class RawStore(Protocol):
    def seen(self, source_id: str, content_hash: str) -> bool: ...

    def put(self, item: RawItem) -> bool:
        """Store; return False if an identical payload already exists."""
        ...

    def items(self, source_id: str) -> Iterator[RawItem]:
        """All stored items for a source, oldest first (id order = time order)."""
        ...

    def latest(self, source_id: str) -> RawItem | None: ...


class FileRawStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._hash_cache: dict[str, set[str]] = {}

    def _hashes(self, source_id: str) -> set[str]:
        if source_id not in self._hash_cache:
            ledger = self._root / source_id / "_hashes.txt"
            self._hash_cache[source_id] = (
                set(ledger.read_text(encoding="utf-8").split()) if ledger.exists() else set()
            )
        return self._hash_cache[source_id]

    def seen(self, source_id: str, content_hash: str) -> bool:
        return content_hash in self._hashes(source_id)

    def put(self, item: RawItem) -> bool:
        if self.seen(item.source_id, item.content_hash):
            return False
        month = item.retrieved_at.strftime("%Y-%m")
        directory = self._root / item.source_id / month
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{item.raw_item_id}.json"
        if path.exists():  # append-only: never overwrite
            raise BiosError(f"raw item collision (should be impossible): {path}")
        path.write_text(item.model_dump_json(indent=2), encoding="utf-8")
        ledger = self._root / item.source_id / "_hashes.txt"
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(item.content_hash + "\n")
        self._hashes(item.source_id).add(item.content_hash)
        return True

    def items(self, source_id: str) -> Iterator[RawItem]:
        base = self._root / source_id
        if not base.is_dir():
            return
        for path in sorted(base.rglob("raw_*.json")):
            yield RawItem.model_validate_json(path.read_text(encoding="utf-8"))

    def latest(self, source_id: str) -> RawItem | None:
        base = self._root / source_id
        if not base.is_dir():
            return None
        paths = sorted(base.rglob("raw_*.json"))
        if not paths:
            return None
        return RawItem.model_validate_json(paths[-1].read_text(encoding="utf-8"))

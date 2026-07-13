"""Dead letter queue: unparsable data is quarantined, never dropped
(MSD §15.4). The raw fetch that produced it is already in the raw store;
the DLQ records *why* it could not be processed, for weekly human review."""

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from bios.common.ids import IdKind
from bios.common.schema import BiosRecord
from bios.common.timeutil import utc_now
from bios.ingestion.rawitem import _pydantic_id  # shared id validator


class DeadLetterRecord(BiosRecord):
    ts: datetime
    source_id: str
    reason: str
    payload_snippet: str = Field(max_length=2000)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        return _pydantic_id(v, IdKind.SOURCE)


class DeadLetterQueue:
    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        source_id: str,
        reason: str,
        payload_snippet: str,
        meta: dict[str, Any] | None = None,
    ) -> DeadLetterRecord:
        record = DeadLetterRecord(
            ts=utc_now(),
            source_id=source_id,
            reason=reason,
            payload_snippet=payload_snippet[:2000],
            meta=meta or {},
        )
        path = self._root / f"{source_id}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")
        return record

    def count(self, source_id: str) -> int:
        path = self._root / f"{source_id}.jsonl"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

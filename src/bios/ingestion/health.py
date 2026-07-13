"""Per-source health tracking (silent data gaps are forbidden — MSD §15.4)."""

from typing import Any

from bios.common.schema import BiosModel
from bios.common.statestore import JsonStateStore
from bios.common.timeutil import utc_now


class SourceHealth(BiosModel):
    source_id: str
    total_runs: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_run_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None


class HealthTracker:
    def __init__(self, store: JsonStateStore) -> None:
        self._store = store

    def _update(self, source_id: str, ok: bool, error: str | None) -> None:
        data = self._store.load()
        entry: dict[str, Any] = data.get(source_id, {"source_id": source_id})
        health = SourceHealth.model_validate(entry)
        now = utc_now().isoformat()
        update = {
            "total_runs": health.total_runs + 1,
            "last_run_at": now,
            "total_failures": health.total_failures + (0 if ok else 1),
            "consecutive_failures": 0 if ok else health.consecutive_failures + 1,
            "last_success_at": now if ok else health.last_success_at,
            "last_error": None if ok else error,
        }
        data[source_id] = health.model_copy(update=update).model_dump()
        self._store.save(data)

    def record_success(self, source_id: str) -> None:
        self._update(source_id, ok=True, error=None)

    def record_failure(self, source_id: str, error: str) -> None:
        self._update(source_id, ok=False, error=error[:500])

    def snapshot(self) -> list[SourceHealth]:
        return sorted(
            (SourceHealth.model_validate(v) for v in self._store.load().values()),
            key=lambda h: h.source_id,
        )

    def degraded(self) -> list[SourceHealth]:
        """Sources currently failing — surfaced in the morning briefing."""
        return [h for h in self.snapshot() if h.consecutive_failures > 0]

"""Per-key circuit breaker (MSD §15.4): N consecutive failures open the
circuit; after a cooldown one half-open trial is allowed. One dying source
must never consume the whole collection window. State is persisted so
breaker memory survives process restarts (we run as short-lived jobs).
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from bios.common.errors import BiosError
from bios.common.statestore import JsonStateStore
from bios.common.timeutil import parse_utc, utc_now

BreakerState = Literal["closed", "open", "half_open"]


class BreakerOpenError(BiosError):
    """Call refused: the circuit is open and still cooling down."""


class CircuitBreaker:
    def __init__(
        self,
        store: JsonStateStore,
        failure_threshold: int = 3,
        cooldown_seconds: float = 21600,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = store
        self._threshold = failure_threshold
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._clock = clock

    def _entry(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        entry: dict[str, Any] = data.get(key) or {"failures": 0, "opened_at": None}
        return entry

    def status(self, key: str) -> BreakerState:
        entry = self._entry(self._store.load(), key)
        opened_at = entry.get("opened_at")
        if opened_at is None:
            return "closed"
        if self._clock() - parse_utc(opened_at) >= self._cooldown:
            return "half_open"
        return "open"

    def check(self, key: str) -> None:
        """Raise BreakerOpenError if the key must not be called now."""
        if self.status(key) == "open":
            raise BreakerOpenError(f"circuit open for {key!r} (cooling down)")

    def record_success(self, key: str) -> None:
        data = self._store.load()
        if key in data:
            del data[key]
            self._store.save(data)

    def record_failure(self, key: str) -> None:
        data = self._store.load()
        entry = self._entry(data, key)
        entry["failures"] = int(entry.get("failures", 0)) + 1
        already_open = entry.get("opened_at") is not None
        if entry["failures"] >= self._threshold or already_open:
            entry["opened_at"] = self._clock().isoformat()  # (re-)open, restart cooldown
        data[key] = entry
        self._store.save(data)

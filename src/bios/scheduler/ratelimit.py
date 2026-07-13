"""Per-key minimum-interval rate limiter (in-process).

Collection is single-process by design (ADR-004); this prevents hammering
one provider when several jobs share a host or a job retries quickly.
"""

import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def acquire(self, key: str, min_interval_seconds: float) -> float:
        """Block until the key may be used again; return seconds waited."""
        waited = 0.0
        last = self._last.get(key)
        if last is not None:
            remaining = min_interval_seconds - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
                waited = remaining
        self._last[key] = self._clock()
        return waited

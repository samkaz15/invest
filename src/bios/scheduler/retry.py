"""Retry with exponential backoff and jitter (MSD §15.4: 1m→5m→30m, max 3).

Delays are injected via config; sleep and rng are injectable for tests.
Only BiosError-family failures are retried by default — programming errors
must crash, not loop.
"""

import random
import time
from collections.abc import Callable, Sequence

from bios.common.errors import BiosError
from bios.common.logutil import get_logger

logger = get_logger(__name__)


class RetryPolicy:
    def __init__(
        self,
        delays_seconds: Sequence[float],
        jitter: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._delays = list(delays_seconds)
        self._jitter = jitter
        self._sleep = sleep
        self._rng = rng

    @property
    def max_attempts(self) -> int:
        return len(self._delays) + 1

    def run[T](
        self,
        fn: Callable[[], T],
        retry_on: tuple[type[BaseException], ...] = (BiosError,),
        label: str = "task",
    ) -> T:
        for attempt in range(self.max_attempts):
            try:
                return fn()
            except retry_on as exc:
                if attempt == len(self._delays):
                    logger.error("%s failed after %d attempts: %s", label, attempt + 1, exc)
                    raise
                delay = self._delays[attempt] * (1 + self._jitter * (2 * self._rng() - 1))
                logger.warning(
                    "%s attempt %d/%d failed (%s); retrying in %.0fs",
                    label,
                    attempt + 1,
                    self.max_attempts,
                    exc,
                    delay,
                )
                self._sleep(delay)
        raise AssertionError("unreachable")

"""Retry / circuit breaker / rate limiter / state store tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bios.common import BiosError
from bios.common.statestore import JsonStateStore
from bios.scheduler.breaker import BreakerOpenError, CircuitBreaker
from bios.scheduler.ratelimit import RateLimiter
from bios.scheduler.retry import RetryPolicy


class Flaky:
    def __init__(self, fail_times: int) -> None:
        self.calls = 0
        self._fail_times = fail_times

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise BiosError(f"boom {self.calls}")
        return "ok"


def _policy(delays: list[float], sleeps: list[float]) -> RetryPolicy:
    return RetryPolicy(delays, jitter=0.1, sleep=sleeps.append, rng=lambda: 1.0)


def test_retry_succeeds_after_failures_with_backoff() -> None:
    sleeps: list[float] = []
    fn = Flaky(fail_times=2)
    assert _policy([60, 300, 1800], sleeps).run(fn) == "ok"
    assert fn.calls == 3
    assert sleeps == [60 * 1.1, 300 * 1.1]  # rng=1.0 -> +jitter exactly


def test_retry_gives_up_after_max_attempts() -> None:
    sleeps: list[float] = []
    fn = Flaky(fail_times=99)
    with pytest.raises(BiosError, match="boom 4"):
        _policy([1, 2, 3], sleeps).run(fn)
    assert fn.calls == 4


def test_retry_does_not_catch_programming_errors() -> None:
    def broken() -> None:
        raise TypeError("bug")

    with pytest.raises(TypeError):
        RetryPolicy([1], sleep=lambda _: None).run(broken)


def test_breaker_opens_blocks_and_half_opens(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)
    breaker = CircuitBreaker(
        JsonStateStore(tmp_path / "b.json"),
        failure_threshold=3,
        cooldown_seconds=3600,
        clock=lambda: now,
    )
    key = "collect_x"
    for _ in range(3):
        breaker.check(key)
        breaker.record_failure(key)
    assert breaker.status(key) == "open"
    with pytest.raises(BreakerOpenError):
        breaker.check(key)
    now += timedelta(hours=2)  # cooldown elapsed -> one trial allowed
    assert breaker.status(key) == "half_open"
    breaker.check(key)
    breaker.record_failure(key)  # trial failed -> re-open, cooldown restarts
    assert breaker.status(key) == "open"
    now += timedelta(hours=2)
    breaker.check(key)
    breaker.record_success(key)  # trial succeeded -> closed
    assert breaker.status(key) == "closed"


def test_breaker_state_survives_restart(tmp_path: Path) -> None:
    store_path = tmp_path / "b.json"
    b1 = CircuitBreaker(JsonStateStore(store_path), failure_threshold=1)
    b1.record_failure("k")
    b2 = CircuitBreaker(JsonStateStore(store_path), failure_threshold=1)
    assert b2.status("k") == "open"


def test_rate_limiter_enforces_min_interval() -> None:
    clock = iter([0.0, 0.5, 1.5]).__next__  # store; elapsed-check; store
    sleeps: list[float] = []
    rl = RateLimiter(clock=clock, sleep=sleeps.append)
    rl.acquire("k", 2.0)  # first call: no wait
    rl.acquire("k", 2.0)  # 0.5s later: must wait 1.5s
    assert sleeps == [1.5]


def test_state_store_atomic_roundtrip_and_corruption(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path / "s.json")
    assert store.load() == {}
    store.save({"a": 1})
    assert store.load() == {"a": 1}
    (tmp_path / "s.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(BiosError, match="corrupt"):
        store.load()

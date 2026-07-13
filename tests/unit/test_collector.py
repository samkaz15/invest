"""Collector and JobRunner end-to-end tests (fake adapter, tmp stores)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bios.audit import AuditLogger, JsonlAuditSink
from bios.common import RunStatus
from bios.common.statestore import JsonStateStore
from bios.config.models import JobSpec, PipelinesConfig, ResilienceDefaults, SourceSpec
from bios.ingestion.adapter import AdapterError, FetchResult, ParseFailure, SourceAdapter
from bios.ingestion.collector import CollectError, Collector
from bios.ingestion.dlq import DeadLetterQueue
from bios.ingestion.health import HealthTracker
from bios.ingestion.rawitem import RawDraft
from bios.ingestion.rawstore import FileRawStore
from bios.scheduler.breaker import CircuitBreaker
from bios.scheduler.jobs import JobRunner
from bios.scheduler.ratelimit import RateLimiter
from bios.scheduler.retry import RetryPolicy

SPEC = SourceSpec(
    source_id="src_fake", name="fake", kind="http_json", url="https://example.com", tier=2
)


class FakeAdapter(SourceAdapter):
    result: FetchResult = FetchResult()
    error: Exception | None = None

    def fetch(self, client: object, conditional: dict[str, str] | None = None) -> FetchResult:
        if FakeAdapter.error is not None:
            raise FakeAdapter.error
        return FakeAdapter.result


@pytest.fixture
def collector(tmp_path: Path) -> Collector:
    FakeAdapter.result, FakeAdapter.error = FetchResult(), None
    return Collector(
        sources={"src_fake": SPEC},
        store=FileRawStore(tmp_path / "raw"),
        client=None,  # type: ignore[arg-type]  # FakeAdapter never touches it
        audit=AuditLogger(JsonlAuditSink(tmp_path / "audit")),
        metrics_sink=JsonlAuditSink(tmp_path / "metrics"),
        dlq=DeadLetterQueue(tmp_path / "dlq"),
        health=HealthTracker(JsonStateStore(tmp_path / "health.json")),
        rate_limiter=RateLimiter(clock=lambda: 0.0, sleep=lambda _: None),
        http_state=JsonStateStore(tmp_path / "http.json"),
        adapter_factory=FakeAdapter,
    )


def test_collect_stores_dedupes_and_audits(collector: Collector, tmp_path: Path) -> None:
    FakeAdapter.result = FetchResult(
        drafts=[
            RawDraft(payload_text='{"n":1}', content_type="application/json"),
            RawDraft(payload_text='{"n":2}', content_type="application/json"),
        ]
    )
    report1 = collector.collect("src_fake")
    assert (report1.stored, report1.duplicates, report1.status) == (2, 0, RunStatus.SUCCESS)
    report2 = collector.collect("src_fake")  # identical refetch -> all duplicates
    assert (report2.stored, report2.duplicates) == (0, 2)
    # observability: metrics + agent_runs streams both written
    metrics = (tmp_path / "metrics" / "collector_metrics.jsonl").read_text().splitlines()
    runs = (tmp_path / "audit" / "agent_runs.jsonl").read_text().splitlines()
    assert len(metrics) == 2 and len(runs) == 2
    assert json.loads(runs[0])["agent"] == "collector.src_fake"


def test_parse_failures_go_to_dlq_as_degraded(collector: Collector, tmp_path: Path) -> None:
    FakeAdapter.result = FetchResult(
        drafts=[RawDraft(payload_text="{}", content_type="application/json")],
        parse_failures=[ParseFailure(reason="bad entry", payload_snippet="<item/>")],
    )
    report = collector.collect("src_fake")
    assert report.status is RunStatus.DEGRADED
    assert collector._dlq.count("src_fake") == 1


def test_fetch_error_records_failure_and_raises(collector: Collector) -> None:
    FakeAdapter.error = AdapterError("unparsable feed")
    with pytest.raises(CollectError):
        collector.collect("src_fake")
    health = collector._health.snapshot()[0]
    assert health.consecutive_failures == 1 and health.last_error is not None


def test_job_runner_due_breaker_and_state(tmp_path: Path) -> None:
    now = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)
    pipelines = PipelinesConfig(
        defaults=ResilienceDefaults(retry_delays_seconds=[0.0], breaker_failure_threshold=2),
        jobs=[
            JobSpec(job_id="j_ok", task="collect", source_id="src_fake", interval_minutes=60),
            JobSpec(
                job_id="j_off",
                task="collect",
                source_id="src_fake",
                interval_minutes=60,
                enabled=False,
            ),
        ],
    )
    calls: list[str] = []

    def task(job: JobSpec) -> None:
        calls.append(job.job_id)
        if fail_mode:
            raise CollectError("down")

    runner = JobRunner(
        pipelines,
        JsonStateStore(tmp_path / "sched.json"),
        CircuitBreaker(JsonStateStore(tmp_path / "brk.json"), 2, 36_000, clock=lambda: now),
        RetryPolicy([0.0], sleep=lambda _: None),
        clock=lambda: now,
    )
    runner.register("collect", task)

    fail_mode = False
    results = runner.run_due()
    assert [r.job_id for r in results] == ["j_ok"]  # disabled job not scheduled
    assert results[0].status is RunStatus.SUCCESS
    assert runner.due_jobs() == []  # just ran -> not due again

    now += timedelta(hours=2)
    fail_mode = True
    assert runner.run_due()[0].status is RunStatus.FAILED  # retry ladder exhausted (2 calls)
    now += timedelta(hours=2)
    runner.run_due()  # second failed run -> breaker threshold reached
    now += timedelta(hours=2)
    assert runner.run_due()[0].status is RunStatus.SKIPPED  # circuit open
    assert calls.count("j_ok") == 1 + 2 + 2  # 1 success + 2 attempts x 2 failed runs

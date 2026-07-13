"""Collector: one source fetch, end to end.

fetch (rate-limited, conditional GET) → hash-dedupe → raw store →
DLQ for unparsable items → health + metrics + audit. Everything a
run did is observable afterwards (Constitution Art.6).
"""

import time
from collections.abc import Callable
from datetime import datetime

from pydantic import Field

from bios.audit import AgentRunRecord, AuditLogger, AuditSink
from bios.common.errors import BiosError
from bios.common.ids import IdKind, new_id
from bios.common.labels import RunStatus
from bios.common.logutil import get_logger
from bios.common.schema import BiosRecord
from bios.common.statestore import JsonStateStore
from bios.common.timeutil import utc_now
from bios.config.models import SourceSpec
from bios.ingestion.adapter import (
    AdapterError,
    FetchResult,
    SourceAdapter,
    conditional_headers,
)
from bios.ingestion.adapters import build_adapter
from bios.ingestion.dlq import DeadLetterQueue
from bios.ingestion.health import HealthTracker
from bios.ingestion.http import HttpClient, TransportError
from bios.ingestion.rawitem import build_raw_item
from bios.ingestion.rawstore import RawStore
from bios.scheduler.ratelimit import RateLimiter

logger = get_logger(__name__)

METRICS_STREAM = "collector_metrics"


class CollectError(BiosError):
    """A collection run failed (retryable at the job level)."""


class CollectReport(BiosRecord):
    """Per-run metrics record (appended to the metrics stream)."""

    run_id: str
    source_id: str
    ts: datetime
    status: RunStatus
    fetched: int = 0
    stored: int = 0
    duplicates: int = 0
    parse_failures: int = 0
    not_modified: bool = False
    duration_ms: int = 0
    error: str | None = None
    stored_ids: list[str] = Field(default_factory=list)  # capped sample for traceability


class Collector:
    def __init__(
        self,
        sources: dict[str, SourceSpec],
        store: RawStore,
        client: HttpClient,
        audit: AuditLogger,
        metrics_sink: AuditSink,
        dlq: DeadLetterQueue,
        health: HealthTracker,
        rate_limiter: RateLimiter,
        http_state: JsonStateStore,
        adapter_factory: Callable[[SourceSpec], SourceAdapter] = build_adapter,
    ) -> None:
        self._sources = sources
        self._store = store
        self._client = client
        self._audit = audit
        self._metrics = metrics_sink
        self._dlq = dlq
        self._health = health
        self._rate = rate_limiter
        self._http_state = http_state
        self._adapter_factory = adapter_factory

    def enabled_source_ids(self) -> list[str]:
        return [sid for sid, spec in self._sources.items() if spec.enabled]

    def collect(self, source_id: str) -> CollectReport:
        spec = self._sources.get(source_id)
        if spec is None:
            raise CollectError(f"unknown source {source_id!r}")
        if not spec.enabled:
            return self._finish(source_id, RunStatus.SKIPPED, utc_now(), time.monotonic())

        started_at, t0 = utc_now(), time.monotonic()
        self._rate.acquire(source_id, spec.min_interval_seconds)
        try:
            result = self._fetch(spec)
        except (AdapterError, TransportError) as exc:
            if isinstance(exc, AdapterError):
                self._dlq.put(source_id, reason=str(exc), payload_snippet="")
            self._health.record_failure(source_id, str(exc))
            self._finish(source_id, RunStatus.FAILED, started_at, t0, error=str(exc))
            raise CollectError(f"collect {source_id} failed: {exc}") from exc

        if result.not_modified:
            self._health.record_success(source_id)
            return self._finish(source_id, RunStatus.SUCCESS, started_at, t0, not_modified=True)

        stored_ids: list[str] = []
        duplicates = 0
        for draft in result.drafts:
            item = build_raw_item(source_id, draft)
            if self._store.put(item):
                stored_ids.append(item.raw_item_id)
            else:
                duplicates += 1
        for failure in result.parse_failures:
            self._dlq.put(source_id, failure.reason, failure.payload_snippet)

        self._save_conditional(source_id, result.etag, result.last_modified)
        self._health.record_success(source_id)
        status = RunStatus.DEGRADED if result.parse_failures else RunStatus.SUCCESS
        return self._finish(
            source_id,
            status,
            started_at,
            t0,
            fetched=len(result.drafts),
            stored=len(stored_ids),
            duplicates=duplicates,
            parse_failures=len(result.parse_failures),
            stored_ids=stored_ids[:20],
        )

    def _fetch(self, spec: SourceSpec) -> FetchResult:
        state = self._http_state.load()
        conditional = conditional_headers(
            state.get(f"{spec.source_id}.etag"), state.get(f"{spec.source_id}.last_modified")
        )
        adapter = self._adapter_factory(spec)
        return adapter.fetch(self._client, conditional or None)

    def _save_conditional(
        self, source_id: str, etag: str | None, last_modified: str | None
    ) -> None:
        if etag is None and last_modified is None:
            return
        state = self._http_state.load()
        if etag:
            state[f"{source_id}.etag"] = etag
        if last_modified:
            state[f"{source_id}.last_modified"] = last_modified
        self._http_state.save(state)

    def _finish(
        self,
        source_id: str,
        status: RunStatus,
        started_at: datetime,
        t0: float,
        **fields: object,
    ) -> CollectReport:
        ended_at = utc_now()
        report = CollectReport(
            run_id=new_id(IdKind.AGENT_RUN),
            source_id=source_id,
            ts=ended_at,
            status=status,
            duration_ms=int((time.monotonic() - t0) * 1000),
            **fields,  # type: ignore[arg-type]
        )
        self._metrics.append(METRICS_STREAM, report)
        self._audit.log_agent_run(
            AgentRunRecord(
                run_id=report.run_id,
                agent=f"collector.{source_id}",
                started_at=started_at,
                ended_at=ended_at,
                prompt_version="-",
                model="-",
                status=status,
                input_refs=[source_id],
                output_refs=report.stored_ids,
                error=report.error,
            )
        )
        logger.info(
            "collect %s: %s fetched=%d stored=%d dup=%d dlq=%d",
            source_id,
            status.value,
            report.fetched,
            report.stored,
            report.duplicates,
            report.parse_failures,
        )
        return report

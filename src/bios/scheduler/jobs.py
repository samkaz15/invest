"""Job runner: interval-due computation, breaker + retry wrapping,
last-run persistence. Designed to be driven by cron/launchd via
``bios run-due`` (ADR-004: no scheduler daemon)."""

from collections.abc import Callable
from datetime import datetime, timedelta

from bios.common.errors import BiosError
from bios.common.labels import RunStatus
from bios.common.logutil import get_logger
from bios.common.schema import BiosModel
from bios.common.statestore import JsonStateStore
from bios.common.timeutil import parse_utc, utc_now
from bios.config.models import JobSpec, PipelinesConfig
from bios.scheduler.breaker import BreakerOpenError, CircuitBreaker
from bios.scheduler.retry import RetryPolicy

logger = get_logger(__name__)

TaskFn = Callable[[JobSpec], None]


class JobResult(BiosModel):
    job_id: str
    status: RunStatus
    detail: str | None = None


class JobRunner:
    def __init__(
        self,
        pipelines: PipelinesConfig,
        state: JsonStateStore,
        breaker: CircuitBreaker,
        retry: RetryPolicy,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._pipelines = pipelines
        self._state = state
        self._breaker = breaker
        self._retry = retry
        self._clock = clock
        self._tasks: dict[str, TaskFn] = {}

    def register(self, task: str, fn: TaskFn) -> None:
        self._tasks[task] = fn

    def due_jobs(self) -> list[JobSpec]:
        state = self._state.load()
        now = self._clock()
        due: list[JobSpec] = []
        for job in self._pipelines.jobs:
            if not job.enabled:
                continue
            last = state.get(f"job.{job.job_id}.last_run")
            if last is None or now - parse_utc(str(last)) >= timedelta(
                minutes=job.interval_minutes
            ):
                due.append(job)
        return due

    def run_job(self, job: JobSpec) -> JobResult:
        fn = self._tasks.get(job.task)
        if fn is None:
            return JobResult(
                job_id=job.job_id, status=RunStatus.FAILED, detail=f"unknown task {job.task!r}"
            )
        try:
            self._breaker.check(job.job_id)
        except BreakerOpenError as exc:
            logger.warning("skipping %s: %s", job.job_id, exc)
            return JobResult(job_id=job.job_id, status=RunStatus.SKIPPED, detail=str(exc))
        try:
            self._retry.run(lambda: fn(job), label=job.job_id)
        except BiosError as exc:
            self._breaker.record_failure(job.job_id)
            self._mark_run(job)  # failed run still consumes its slot (retry ladder already ran)
            return JobResult(job_id=job.job_id, status=RunStatus.FAILED, detail=str(exc)[:500])
        self._breaker.record_success(job.job_id)
        self._mark_run(job)
        return JobResult(job_id=job.job_id, status=RunStatus.SUCCESS)

    def run_due(self) -> list[JobResult]:
        results = [self.run_job(job) for job in self.due_jobs()]
        failed = [r for r in results if r.status is RunStatus.FAILED]
        logger.info("run_due: %d jobs, %d failed", len(results), len(failed))
        return results

    def _mark_run(self, job: JobSpec) -> None:
        state = self._state.load()
        state[f"job.{job.job_id}.last_run"] = self._clock().isoformat()
        self._state.save(state)

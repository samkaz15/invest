"""Composition root and CLI.

The only module allowed to import from every layer: it wires Settings +
config into concrete objects. Commands are cron/launchd entry points:

    python -m bios.cli collect --source src_coindesk_rss
    python -m bios.cli run-due
    python -m bios.cli health
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass

from bios.audit import AuditLogger, JsonlAuditSink
from bios.common.errors import BiosError
from bios.common.logutil import get_logger, setup_logging
from bios.common.statestore import JsonStateStore
from bios.config import ConfigRoot, Settings, load_config
from bios.config.models import JobSpec, SourceSpec
from bios.ingestion.collector import CollectError, Collector
from bios.ingestion.dlq import DeadLetterQueue
from bios.ingestion.health import HealthTracker
from bios.ingestion.http import HttpClient
from bios.ingestion.rawstore import FileRawStore
from bios.scheduler.breaker import CircuitBreaker
from bios.scheduler.jobs import JobRunner
from bios.scheduler.ratelimit import RateLimiter
from bios.scheduler.retry import RetryPolicy

logger = get_logger(__name__)

_ENV_REF = re.compile(r"\$\{(\w+)\}")


def _expand_env(text: str, missing: list[str]) -> str:
    def sub(match: re.Match[str]) -> str:
        value = os.environ.get(match.group(1))
        if value is None:
            missing.append(match.group(1))
            return match.group(0)
        return value

    return _ENV_REF.sub(sub, text)


def resolve_sources(sources: dict[str, SourceSpec]) -> dict[str, SourceSpec]:
    """Expand ${ENV_VAR} in urls/headers. Sources with missing secrets are
    disabled (not fatal): a missing API key must not stop other collection,
    but it must be visible."""
    resolved: dict[str, SourceSpec] = {}
    for source_id, spec in sources.items():
        missing: list[str] = []
        url = _expand_env(spec.url, missing)
        headers = {k: _expand_env(v, missing) for k, v in spec.headers.items()}
        if missing and spec.enabled:
            logger.warning("disabling %s: missing env %s", source_id, sorted(set(missing)))
            resolved[source_id] = spec.model_copy(update={"enabled": False})
        else:
            resolved[source_id] = spec.model_copy(update={"url": url, "headers": headers})
    return resolved


@dataclass
class App:
    settings: Settings
    config: ConfigRoot
    collector: Collector
    runner: JobRunner
    health: HealthTracker
    dlq: DeadLetterQueue


def build_app(settings: Settings | None = None) -> App:
    settings = settings or Settings()
    setup_logging(settings.log_level, settings.log_json)
    config = load_config(settings.config_dir)

    var = settings.var_dir
    audit = AuditLogger(JsonlAuditSink(settings.audit_dir))
    metrics_sink = JsonlAuditSink(var / "metrics")
    health = HealthTracker(JsonStateStore(var / "state" / "health.json"))
    dlq = DeadLetterQueue(var / "dlq")
    collector = Collector(
        sources=resolve_sources(config.sources),
        store=FileRawStore(var / "raw"),
        client=HttpClient(),
        audit=audit,
        metrics_sink=metrics_sink,
        dlq=dlq,
        health=health,
        rate_limiter=RateLimiter(),
        http_state=JsonStateStore(var / "state" / "http.json"),
    )

    defaults = config.pipelines.defaults
    runner = JobRunner(
        pipelines=config.pipelines,
        state=JsonStateStore(var / "state" / "scheduler.json"),
        breaker=CircuitBreaker(
            JsonStateStore(var / "state" / "breakers.json"),
            failure_threshold=defaults.breaker_failure_threshold,
            cooldown_seconds=defaults.breaker_cooldown_minutes * 60,
        ),
        retry=RetryPolicy(defaults.retry_delays_seconds, defaults.retry_jitter),
    )

    def collect_task(job: JobSpec) -> None:
        assert job.source_id is not None  # validated at config load
        collector.collect(job.source_id)

    runner.register("collect", collect_task)
    return App(settings, config, collector, runner, health, dlq)


def _cmd_collect(app: App, source: str | None) -> int:
    source_ids = [source] if source else app.collector.enabled_source_ids()
    failures = 0
    for source_id in source_ids:
        try:
            app.collector.collect(source_id)
        except CollectError as exc:
            failures += 1
            logger.error("%s", exc)
    return 1 if failures else 0


def _cmd_health(app: App) -> int:
    for h in app.health.snapshot():
        flag = "!!" if h.consecutive_failures else "ok"
        print(
            f"[{flag}] {h.source_id}: runs={h.total_runs} fail={h.total_failures} "
            f"consecutive={h.consecutive_failures} last_success={h.last_success_at} "
            f"dlq={app.dlq.count(h.source_id)}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bios")
    sub = parser.add_subparsers(dest="command", required=True)
    p_collect = sub.add_parser("collect", help="collect one source (or all enabled)")
    p_collect.add_argument("--source", default=None)
    sub.add_parser("run-due", help="run all due scheduled jobs (cron entry point)")
    sub.add_parser("health", help="print per-source health and DLQ counts")
    args = parser.parse_args(argv)

    try:
        app = build_app()
        if args.command == "collect":
            return _cmd_collect(app, args.source)
        if args.command == "run-due":
            results = app.runner.run_due()
            return 1 if any(r.status.value == "failed" for r in results) else 0
        if args.command == "health":
            return _cmd_health(app)
    except BiosError as exc:
        logger.error("fatal: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Composition root and CLI.

The only module allowed to import from every layer: it wires Settings +
config into concrete objects. Commands are entry points for GitHub
Actions (and for a human at a terminal):

    python -m mios.cli collect --source src_fred_dgs10
    python -m mios.cli run-due
    python -m mios.cli health

Phase 2 deliberately exposes only the commands whose implementation
survived the BIOS→MIOS cleanup. Forecast, analysis and report commands
arrive with their layers in Phases 5-9; a command is added when the code
behind it exists, never before (docs/REPOSITORY_AUDIT.md §8 U-1..U-4).
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass

from mios.audit import AuditLogger, JsonlAuditSink
from mios.common.errors import MiosError
from mios.common.logutil import get_logger, setup_logging
from mios.common.statestore import JsonStateStore
from mios.config import ConfigRoot, Settings, load_config
from mios.config.models import JobSpec, SourceSpec
from mios.extraction.news import NewsExtractor
from mios.ingestion.collector import CollectError, Collector
from mios.ingestion.dlq import DeadLetterQueue
from mios.ingestion.health import HealthTracker
from mios.ingestion.http import HttpClient
from mios.ingestion.rawstore import FileRawStore
from mios.knowledge.store import CurationQueue
from mios.scheduler.breaker import CircuitBreaker
from mios.scheduler.jobs import JobRunner
from mios.scheduler.ratelimit import RateLimiter
from mios.scheduler.retry import RetryPolicy
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources

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
    db: Database
    raw_store: FileRawStore


def build_app(settings: Settings | None = None) -> App:
    settings = settings or Settings()
    setup_logging(settings.log_level, settings.log_json)
    config = load_config(settings.config_dir)

    var = settings.var_dir
    audit = AuditLogger(JsonlAuditSink(settings.audit_dir))
    metrics_sink = JsonlAuditSink(var / "metrics")
    health = HealthTracker(JsonStateStore(var / "state" / "health.json"))
    dlq = DeadLetterQueue(var / "dlq")
    db = Database(settings.database_url)
    raw_store = FileRawStore(settings.raw_dir)
    collector = Collector(
        sources=resolve_sources(config.sources),
        store=raw_store,
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
    return App(settings, config, collector, runner, health, dlq, db, raw_store)


def _cmd_migrate(app: App) -> int:
    applied = MigrationRunner(app.db, app.settings.migrations_dir).apply_all()
    # Sync the *resolved* registry: sources auto-disabled by missing secrets
    # must be recorded as disabled so reports can disclose the gap.
    n = sync_sources(app.db, resolve_sources(app.config.sources))
    print(f"migrations applied: {applied or 'none (up to date)'}; sources synced: {n}")
    return 0


def _cmd_extract(app: App) -> int:
    extractor = NewsExtractor(app.db, app.raw_store, CurationQueue(app.db), app.config.sources)
    stats = extractor.run()
    print(f"news candidates queued: {stats['queued']} (duplicates skipped: {stats['duplicate']})")
    return 0


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
    """Per-source health. Exit code is non-zero when a source is failing, so
    a scheduled run surfaces data gaps instead of reporting silent success
    (docs/REPOSITORY_AUDIT.md §13.3-5)."""
    degraded = 0
    for h in app.health.snapshot():
        flag = "!!" if h.consecutive_failures else "ok"
        degraded += 1 if h.consecutive_failures else 0
        print(
            f"[{flag}] {h.source_id}: runs={h.total_runs} fail={h.total_failures} "
            f"consecutive={h.consecutive_failures} last_success={h.last_success_at} "
            f"dlq={app.dlq.count(h.source_id)}"
        )
    disabled = [s for s in app.collector.disabled_source_ids()]
    for source_id in disabled:
        print(f"[--] {source_id}: disabled (missing secret or turned off in config)")
    return 1 if degraded else 0


def _cmd_sources(app: App) -> int:
    """List the registry as the collector actually sees it.

    Resolved, not as-written: a source whose ${ENV_VAR} is unset is disabled
    at runtime, and printing the config's optimistic `enabled: true` would
    hide exactly the gap this command exists to show.
    """
    for source_id, spec in sorted(resolve_sources(app.config.sources).items()):
        state = "enabled" if spec.enabled else "DISABLED"
        print(f"{source_id:<28} T{spec.tier} {spec.kind:<10} {state:<9} {spec.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mios")
    sub = parser.add_subparsers(dest="command", required=True)
    p_collect = sub.add_parser("collect", help="collect one source (or all enabled)")
    p_collect.add_argument("--source", default=None)
    sub.add_parser("run-due", help="run all due scheduled jobs (scheduler entry point)")
    sub.add_parser("health", help="print per-source health and DLQ counts")
    sub.add_parser("sources", help="list the configured source registry")
    sub.add_parser("migrate", help="apply pending DB migrations and sync source registry")
    sub.add_parser("extract", help="turn unprocessed news raw items into curation candidates")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    try:
        app = build_app()
        if args.command == "collect":
            return _cmd_collect(app, args.source)
        if args.command == "run-due":
            results = app.runner.run_due()
            return 1 if any(r.status.value == "failed" for r in results) else 0
        if args.command == "health":
            return _cmd_health(app)
        if args.command == "sources":
            return _cmd_sources(app)
        if args.command == "migrate":
            return _cmd_migrate(app)
        if args.command == "extract":
            return _cmd_extract(app)
    except MiosError as exc:
        logger.error("fatal: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

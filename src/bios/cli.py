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

from bios.analysis.base import DimensionAnalyzer
from bios.analysis.derivatives import DerivativesAnalyzer
from bios.analysis.news_flow import NewsFlowAnalyzer
from bios.analysis.onchain import OnchainAnalyzer
from bios.analysis.reactions import ReactionBatch
from bios.analysis.repo import AnalysisRepo
from bios.audit import AuditLogger, JsonlAuditSink
from bios.common.errors import BiosError
from bios.common.logutil import get_logger, setup_logging
from bios.common.statestore import JsonStateStore
from bios.common.timeutil import utc_now
from bios.config import ConfigRoot, Settings, load_config
from bios.config.models import JobSpec, SourceSpec
from bios.extraction.market import MarketNormalizer
from bios.extraction.news import NewsExtractor
from bios.history.seeds import SeedLoader
from bios.ingestion.collector import CollectError, Collector
from bios.ingestion.dlq import DeadLetterQueue
from bios.ingestion.health import HealthTracker
from bios.ingestion.http import HttpClient
from bios.ingestion.rawstore import FileRawStore
from bios.knowledge.curation import approve_candidate
from bios.knowledge.graph import ChainRepo, EntityRepo
from bios.knowledge.snapshots import SnapshotRepo
from bios.knowledge.store import CurationQueue, EventStore
from bios.scheduler.breaker import CircuitBreaker
from bios.scheduler.jobs import JobRunner
from bios.scheduler.ratelimit import RateLimiter
from bios.scheduler.retry import RetryPolicy
from bios.storage.db import Database
from bios.storage.migrate import MigrationRunner
from bios.storage.sync import sync_sources

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
    raw_store = FileRawStore(var / "raw")
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
    n = sync_sources(app.db, app.config.sources)
    print(f"migrations applied: {applied or 'none (up to date)'}; sources synced: {n}")
    return 0


def _cmd_extract(app: App) -> int:
    extractor = NewsExtractor(app.db, app.raw_store, CurationQueue(app.db), app.config.sources)
    stats = extractor.run()
    print(f"news candidates queued: {stats['queued']} (duplicates skipped: {stats['duplicate']})")
    return 0


def _cmd_snapshot(app: App) -> int:
    for asset_id in app.config.assets:
        normalizer = MarketNormalizer(app.raw_store, SnapshotRepo(app.db), asset_id)
        result = normalizer.build_snapshot()
        print(
            f"{asset_id} @ {result['ts'].isoformat()}: price={result['price_usd']} "
            f"metrics={len(result['metrics'])} gaps={len(result['gaps'])}"
        )
        for gap in result["gaps"]:
            print(f"  gap: {gap}")
    return 0


def _cmd_seed(app: App) -> int:
    loader = SeedLoader(
        app.db,
        EventStore(app.db, app.config.events),
        EntityRepo(app.db),
        ChainRepo(app.db),
    )
    counts = loader.load_dir(app.settings.seeds_dir)
    print(f"seeds: {counts}")
    return 0


def _cmd_analyze(app: App) -> int:
    from datetime import timedelta

    repo = AnalysisRepo(app.db)
    queue = CurationQueue(app.db)
    as_of = utc_now()
    for asset_id in app.config.assets:
        history = SnapshotRepo(app.db).range(asset_id, as_of - timedelta(days=90), as_of)
        analyzers: list[DimensionAnalyzer] = [
            DerivativesAnalyzer(),
            OnchainAnalyzer(),
            NewsFlowAnalyzer(queue_stats={"pending": len(queue.pending(limit=1000))}),
        ]
        for analyzer in analyzers:
            report = analyzer.analyze(asset_id, as_of, history)
            repo.save_report(report)
            print(
                f"{asset_id} {report.dimension.value}: score={report.score:+d} "
                f"conviction={report.conviction:.2f} signals={len(report.signals)} "
                f"gaps={len(report.data_gaps)}"
            )
            for finding in report.key_findings:
                print(f"  - {finding}")
    return 0


def _cmd_react(app: App) -> int:
    batch = ReactionBatch(app.db, AnalysisRepo(app.db))
    for asset_id in app.config.assets:
        stats = batch.run(asset_id)
        print(
            f"{asset_id}: reactions computed={stats['computed']} "
            f"pre-snapshot events skipped={stats['events_without_base']}"
        )
    return 0


def _cmd_curate(app: App, args: argparse.Namespace) -> int:
    queue = CurationQueue(app.db)
    if args.curate_command == "list":
        for c in queue.pending(limit=args.limit):
            payload = c["payload"]
            print(f"{c['candidate_id']}  [T{payload.get('tier')}] {payload.get('title')}")
            print(f"    {payload.get('link')}")
        return 0
    if args.curate_command == "approve":
        candidate = app.db.query_one(
            "SELECT * FROM curation_queue WHERE candidate_id=%(c)s AND status='pending'",
            {"c": args.id},
        )
        if candidate is None:
            logger.error("no pending candidate %s", args.id)
            return 1
        event = approve_candidate(
            EventStore(app.db, app.config.events),
            queue,
            candidate,
            event_type=args.type,
            magnitude=args.magnitude,
            title=args.title,
            summary_fact=args.summary,
            slug=args.slug,
        )
        print(f"approved -> {event.event_id} ({event.type}, magnitude {args.magnitude})")
        return 0
    if args.curate_command == "reject":
        queue.resolve(args.id, "rejected", note=args.note)
        print(f"rejected {args.id}")
        return 0
    return 1


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
    sub.add_parser("migrate", help="apply pending DB migrations and sync source registry")
    sub.add_parser("extract", help="turn unprocessed news raw items into curation candidates")
    sub.add_parser("snapshot", help="normalize latest market raw data into a snapshot row")
    sub.add_parser("seed", help="load seeds/chains into the historical database")
    sub.add_parser("analyze", help="run dimension analyzers and store reports")
    sub.add_parser("react", help="stamp market reactions (+1h..+90d) onto events")
    p_curate = sub.add_parser("curate", help="process the curation queue (human loop)")
    curate_sub = p_curate.add_subparsers(dest="curate_command", required=True)
    p_list = curate_sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=10)
    p_approve = curate_sub.add_parser("approve")
    p_approve.add_argument("id")
    p_approve.add_argument("--type", required=True, help="taxonomy type (domain.category.type)")
    p_approve.add_argument("--magnitude", type=int, required=True, choices=range(1, 6))
    p_approve.add_argument("--title", default=None)
    p_approve.add_argument("--summary", default=None)
    p_approve.add_argument("--slug", default=None)
    p_reject = curate_sub.add_parser("reject")
    p_reject.add_argument("id")
    p_reject.add_argument("--note", default="")
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
        if args.command == "migrate":
            return _cmd_migrate(app)
        if args.command == "extract":
            return _cmd_extract(app)
        if args.command == "snapshot":
            return _cmd_snapshot(app)
        if args.command == "seed":
            return _cmd_seed(app)
        if args.command == "analyze":
            return _cmd_analyze(app)
        if args.command == "react":
            return _cmd_react(app)
        if args.command == "curate":
            return _cmd_curate(app, args)
    except BiosError as exc:
        logger.error("fatal: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Composition root and CLI.

The only module allowed to import from every layer: it wires Settings +
config into concrete objects. Commands are entry points for GitHub
Actions (and for a human at a terminal):

    python -m mios.cli collect --source src_fred_dgs10
    python -m mios.cli run-due
    python -m mios.cli health

A command exists only when the code behind it does: forecast, analysis and
report commands arrive with their layers in Phases 5-9, not before
(docs/REPOSITORY_AUDIT.md §8 U-1..U-4).
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass

from mios.analysis.macro import MacroScore, asset_view, score_dimension
from mios.analysis.repo import MacroScoreRepo
from mios.audit import AuditLogger, AuditSink, JsonlAuditSink, PostgresAuditSink, TeeAuditSink
from mios.common.errors import MiosError
from mios.common.logutil import get_logger, setup_logging
from mios.common.statestore import JsonStateStore
from mios.common.timeutil import parse_utc, utc_now
from mios.config import ConfigRoot, Settings, load_config
from mios.config.models import JobSpec, SourceSpec
from mios.extraction.news import NewsExtractor
from mios.ingestion.collector import CollectError, Collector
from mios.ingestion.dlq import DeadLetterQueue
from mios.ingestion.health import HealthTracker
from mios.ingestion.http import HttpClient
from mios.ingestion.rawstore import FileRawStore
from mios.knowledge.store import CurationQueue
from mios.prediction.bridge import forecast_target
from mios.prediction.repo import ForecastRepo
from mios.reports.daily import write_report
from mios.scheduler.breaker import CircuitBreaker
from mios.scheduler.jobs import JobRunner
from mios.scheduler.ratelimit import RateLimiter
from mios.scheduler.retry import RetryPolicy
from mios.series.normalize import Normalizer
from mios.series.repo import ObservationRepo, SeriesRepo
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources
from mios.validation.metrics import MIN_SAMPLE, MetricsReader
from mios.validation.scoring import Scorer

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
    db = Database(settings.database_url)
    # Files for local greppability, the database for durability: an Actions
    # runner is destroyed after the run, and an audit trail that dies with
    # it is not an audit trail (docs/ARCHITECTURE.md §6 A-1).
    sinks: list[AuditSink] = [JsonlAuditSink(settings.audit_dir)]
    if db.ping():
        sinks.append(PostgresAuditSink(db.execute))
    else:
        logger.warning("database unreachable: audit records will only be written to files")
    audit = AuditLogger(TeeAuditSink(*sinks))
    metrics_sink = JsonlAuditSink(var / "metrics")
    health = HealthTracker(JsonStateStore(var / "state" / "health.json"))
    dlq = DeadLetterQueue(var / "dlq")
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
    series = SeriesRepo(app.db).sync(app.config.series.series)
    print(
        f"migrations applied: {applied or 'none (up to date)'}; "
        f"sources synced: {n}; series synced: {series}"
    )
    return 0


def _cmd_normalize(app: App, series_id: str | None) -> int:
    """Turn collected payloads into vintage-keyed observations.

    Exits non-zero on any parse failure. A run that could not read a
    provider's response is not a successful run, and reporting it as one is
    how a dead source becomes invisible (CONSTITUTION.md Art.4-4).
    """
    normalizer = Normalizer(app.db, app.raw_store, app.config.series, ObservationRepo(app.db))
    report = normalizer.run(series_id)
    print(
        f"normalize: raw_items={report.raw_items} written={report.written} "
        f"unchanged={report.skipped} revisions={report.revisions}"
    )
    for failure in report.failures:
        print(f"  FAILED: {failure}")
    return 0 if report.ok else 1


def _cmd_series(app: App) -> int:
    """The series registry with its actual coverage.

    Coverage comes from the database, so a series that is configured but
    has never produced an observation prints as a gap rather than as a
    line item that looks like data.
    """
    coverage = {row["series_id"]: row for row in ObservationRepo(app.db).coverage()}
    gaps = 0
    for spec in sorted(
        app.config.series.series, key=lambda s: (s.country, s.category, s.series_id)
    ):
        row = coverage.get(spec.series_id)
        vintages = int(row["vintages"]) if row else 0
        gaps += 1 if vintages == 0 else 0
        latest = row["latest_period"] if row and row["latest_period"] else "-"
        # Whether a vintage means "when it was published" or only "when we
        # fetched it" changes what a backtest of this series is worth, so it
        # belongs on the line rather than in the config file.
        vintage_kind = "published" if spec.parser.startswith("alfred") else "fetched"
        print(
            f"{spec.series_id:<34} {spec.country} {spec.category:<11} {spec.frequency:<9} "
            f"{'revisable' if spec.revisable else 'final':<9} {vintage_kind:<9} "
            f"rows={vintages:<6} latest={latest}"
        )
    print(f"\n{len(app.config.series.series)} series, {gaps} with no data yet")
    return 0


def _cmd_observations(app: App, series_id: str, as_of: str | None, limit: int) -> int:
    """Print a series as it was knowable at an instant.

    `--as-of` defaults to now for interactive use, but the repository API it
    calls has no default: reproducing a past view must be an explicit act.
    """
    cutoff = parse_utc(as_of) if as_of else utc_now()
    rows = ObservationRepo(app.db).as_of(series_id, cutoff)
    if not rows:
        print(f"{series_id}: no observations knowable at {cutoff.isoformat()}")
        return 0
    print(f"{series_id} as of {cutoff.isoformat()} ({len(rows)} periods)")
    for obs in rows[-limit:]:
        value = "(no figure published)" if obs.value is None else obs.value
        revision = f" rev{obs.revision_n}" if obs.revision_n else ""
        print(f"  {obs.observation_date}  {value}{revision}  vintage={obs.vintage_at.isoformat()}")
    return 0


def _cmd_forecast(app: App, as_of: str | None) -> int:
    """Run every configured forecast and record today's vintage.

    `--as-of` replays a past day: the forecast is built only from data that
    was knowable then, which is what makes a backtested call comparable to
    a live one. `predicted_at` follows the cutoff so the replayed row sits
    in history where it belongs rather than claiming to have been made
    today.
    """
    repo = ObservationRepo(app.db)
    journal = ForecastRepo(app.db)
    cutoff = parse_utc(as_of) if as_of else utc_now()
    produced = recorded = 0
    for target in app.config.forecast.targets:
        forecast = forecast_target(repo, target, as_of=cutoff, predicted_at=cutoff)
        if forecast is None:
            print(f"{target.series_id}: not enough history as of {cutoff.date()} — no forecast")
            continue
        produced += 1
        stored = journal.save(forecast)
        recorded += 1 if stored else 0
        mark = "recorded" if stored else "already recorded today (left untouched)"
        print(
            f"{target.label} {forecast.target_period}: "
            f"{forecast.point_value:+.4f} {target.unit_label} "
            f"(baseline {forecast.baseline_value:+.4f}, "
            f"adjustment {forecast.adjustment:+.4f}) "
            f"confidence={forecast.confidence:.2f} — {mark}"
        )
        if forecast.upside_prob is not None and forecast.downside_prob is not None:
            print(
                f"    上振れ {forecast.upside_prob:.0%} / "
                f"下振れ {forecast.downside_prob:.0%} (vs baseline)"
            )
        for driver in sorted(forecast.drivers, key=lambda d: -abs(d.contribution))[:4]:
            print(f"    driver  {driver.rationale}")
        for contradiction in forecast.contradictions:
            print(f"    against {contradiction}")
        for gap in forecast.data_gaps:
            print(f"    gap     {gap}")
    print(f"\n{produced} forecast(s) produced, {recorded} newly recorded")
    return 0


def _cmd_forecasts(app: App, series_id: str, period: str) -> int:
    """Every forecast ever made for one period, oldest first.

    The question the predictions table exists to answer: what did we think,
    and when did we change our mind?
    """
    rows = ForecastRepo(app.db).vintages(series_id, parse_utc(f"{period}T00:00:00Z").date())
    if not rows:
        print(f"{series_id} {period}: no forecasts recorded")
        return 0
    print(f"{series_id} for {period} — {len(rows)} vintage(s)")
    previous: float | None = None
    for row in rows:
        point = float(row["point_value"]) if row["point_value"] is not None else None
        change = ""
        if point is not None and previous is not None:
            change = f"  ({point - previous:+.4f} vs previous)"
        print(
            f"  {row['predicted_at'].date()}  {point:+.4f}"
            f"  confidence={float(row['confidence']):.2f}"
            f"  method={row['method_version']}{change}"
        )
        previous = point
    return 0


def _cmd_analyze(app: App, as_of: str | None) -> int:
    """Score the macro dimensions and build the two asset views.

    The views are interpretations of macro conditions, not price forecasts —
    MIOS does not forecast prices (CONSTITUTION.md Art.10). Each one prints
    what it cannot see alongside what it can, because a reader who is not
    told will read the model's silence as absence.
    """
    cutoff = parse_utc(as_of) if as_of else utc_now()
    observations = ObservationRepo(app.db)
    repo = MacroScoreRepo(app.db)
    config = app.config.analysis

    scores: dict[str, MacroScore] = {}
    for dimension_spec in config.dimensions:
        score = score_dimension(observations, dimension_spec, cutoff)
        scores[dimension_spec.dimension] = score
        repo.save(score)
        gaps = f"  gaps={len(score.data_gaps)}" if score.data_gaps else ""
        print(
            f"{dimension_spec.label:<24} {score.score:+6.0f}  {score.stance:<12} "
            f"confidence={score.confidence:.2f}  signals={len(score.signals)}{gaps}"
        )

    print()
    for view_spec in config.views:
        view = asset_view(view_spec, scores, cutoff)
        repo.save(view)
        print(
            f"■ {view_spec.label}: {view.score:+.0f} ({view.stance}) "
            f"confidence={view.confidence:.2f}"
        )
        for signal in sorted(view.signals, key=lambda s: -abs(s.points)):
            print(f"    {signal.points:+4d}pt  {signal.rationale}")
        for contradiction in view.contradictions:
            print(f"    against  {contradiction}")
        for gap in view.data_gaps:
            print(f"    gap      {gap}")
        print("    見えていないもの:")
        for blind in view.blind_spots:
            print(f"      - {blind}")
        print()
    return 0


#: The daily chain, in order. Kept here rather than in a Makefile or a
#: workflow because it existed in two places once and they drifted: the
#: workflow tolerated a failing collection and still wrote the report, while
#: `make daily-report` stopped at the first error and produced nothing. One
#: definition, called by both.
#:
#: ``tolerant`` marks the steps where one dead provider must not cost the
#: day's snapshot. The report is not tolerant — if it cannot be written there
#: is nothing left worth committing — and it runs whatever else failed,
#: because it names every gap on its face and is most valuable on exactly
#: those days.
DAILY_CHAIN: list[tuple[str, bool]] = [
    ("migrate", False),
    ("collect", True),
    ("normalize", True),
    ("forecast", True),
    ("analyze", True),
    ("validate", True),
    ("report", False),
]


def _cmd_daily(app: App, as_of: str | None) -> int:
    """Run the whole daily chain, then fail if any step broke.

    Failing at the end rather than at the first error is deliberate: the
    report is the artifact that documents what went wrong, so aborting early
    would throw away the evidence.
    """
    takes_as_of = {"forecast", "analyze", "validate", "report"}
    outcomes: list[tuple[str, str]] = []
    for step, tolerant in DAILY_CHAIN:
        argv = [step, *(["--as-of", as_of] if as_of and step in takes_as_of else [])]
        print(f"\n── {step} " + "─" * (60 - len(step)))
        try:
            code = _dispatch(app, _parse(argv))
        except MiosError as exc:
            logger.error("%s: %s", step, exc)
            code = 2
        outcomes.append((step, "ok" if code == 0 else "FAILED"))
        if code != 0 and not tolerant:
            outcomes.extend((remaining, "skipped") for remaining, _ in DAILY_CHAIN[len(outcomes) :])
            break

    print("\n── summary " + "─" * 52)
    for step, outcome in outcomes:
        print(f"  {step:<12} {outcome}")
    failed = [step for step, outcome in outcomes if outcome == "FAILED"]
    if failed:
        print(
            f"\n{len(failed)} step(s) failed: {', '.join(failed)}.\n"
            "欠損している系列と失敗したソースは、生成済みレポートの "
            "「Data Quality / Missing Data」に記載されている。"
        )
        return 1
    return 0


def _cmd_report(app: App, as_of: str | None) -> int:
    """Write reports/daily/YYYY-MM-DD.md from what is already stored."""
    cutoff = parse_utc(as_of) if as_of else utc_now()
    path = write_report(app.db, app.config, cutoff, app.settings.reports_dir)
    print(f"report written: {path}")
    return 0


def _cmd_validate(app: App, as_of: str | None) -> int:
    """Score every forecast whose target period has since printed.

    Idempotent: a forecast already scored is left alone, so this can run
    daily without rewriting evidence.
    """
    cutoff = parse_utc(as_of) if as_of else utc_now()
    scorer = Scorer(app.db, ObservationRepo(app.db), app.config.forecast.by_id())
    report = scorer.run(cutoff)
    print(
        f"validate: newly scored={report.scored} "
        f"awaiting actuals={report.unresolved} already scored={report.already_scored}"
    )
    return 0


def _cmd_accuracy(app: App, series_id: str | None) -> int:
    """The scoreboard.

    Leads with how much evidence exists, because until that is in the
    dozens every figure below it is an anecdote — and a precise-looking
    table built on four rows is worse than an honest "not yet".
    """
    reader = MetricsReader(app.db)
    coverage = reader.coverage()
    print(
        f"scored forecasts: {coverage['scored']} "
        f"across {coverage['targets']} target(s) and {coverage['periods']} period(s); "
        f"{coverage['awaiting_actuals']} still awaiting actuals"
    )
    if coverage["scored"] == 0:
        print("\n（まだ採点できる予測がありません — 対象期間が発表されてから採点されます）")
        return 0

    print(f"\n{'target':<32} {'horizon':<8} {'n':>4}  {'MAE':>9} {'baseline':>9} {'skill':>9}  dir")
    for row in reader.accuracy(series_id):
        if not row.sufficient:
            print(
                f"{row.target_series_id:<32} {row.horizon:<8} {row.n:>4}  "
                f"（n<{MIN_SAMPLE} のため未算出）"
            )
            continue
        verdict = "beats naive" if row.beats_naive else "loses to naive"
        direction = (
            f"{row.directional_accuracy:.0%}" if row.directional_accuracy is not None else "  -"
        )
        print(
            f"{row.target_series_id:<32} {row.horizon:<8} {row.n:>4}  "
            f"{row.mae:>9.5f} {row.baseline_mae:>9.5f} {row.skill:>+9.5f}  "
            f"{direction}  {verdict}"
        )

    buckets = reader.calibration(series_id)
    graded = sum(b.n for b in buckets)
    print("\ncalibration — 「上振れ N%」と言った時、実際に何%上振れしたか")
    if graded < MIN_SAMPLE:
        # Bins of one or two are arithmetic, not evidence. Saying so beside
        # the table is the difference between a reader learning something
        # and a reader being misled by a precise-looking percentage.
        print(
            f"  （確率つき採点済み予測は {graded} 件のみ。"
            f"{MIN_SAMPLE} 件に満たないため過信/過小の判定は保留）"
        )
    for bucket in buckets:
        if bucket.n == 0:
            continue
        note = ""
        if bucket.overconfident is True:
            note = "  ← 過信"
        elif bucket.overconfident is False:
            note = "  ← 過小"
        realised = f"{bucket.realised:.0%}" if bucket.realised is not None else "-"
        stated = f"{bucket.stated:.0%}" if bucket.stated is not None else "-"
        print(
            f"  {bucket.lower:.0%}-{min(bucket.upper, 1.0):.0%}  n={bucket.n:<4} "
            f"stated={stated:<5} realised={realised}{note}"
        )
    return 0


def _cmd_revisions(app: App, series_id: str, period: str) -> int:
    """Every vintage of one reference period — what we thought, and when."""
    rows = ObservationRepo(app.db).revisions(series_id, parse_utc(f"{period}T00:00:00Z").date())
    if not rows:
        print(f"{series_id} {period}: no observations")
        return 0
    for obs in rows:
        value = "(no figure published)" if obs.value is None else obs.value
        print(f"  rev{obs.revision_n}  {value}  known from {obs.vintage_at.isoformat()}")
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


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mios")
    sub = parser.add_subparsers(dest="command", required=True)
    p_collect = sub.add_parser("collect", help="collect one source (or all enabled)")
    p_collect.add_argument("--source", default=None)
    sub.add_parser("run-due", help="run all due scheduled jobs (scheduler entry point)")
    sub.add_parser("health", help="print per-source health and DLQ counts")
    sub.add_parser("sources", help="list the configured source registry")
    sub.add_parser("migrate", help="apply pending DB migrations and sync source registry")
    sub.add_parser("extract", help="turn unprocessed news raw items into curation candidates")
    p_norm = sub.add_parser("normalize", help="raw payloads -> vintage-keyed observations")
    p_norm.add_argument("--series", default=None, help="normalize only this series_id")
    sub.add_parser("series", help="the series registry and how much data each one has")
    p_obs = sub.add_parser("observations", help="a series as it was knowable at an instant")
    p_obs.add_argument("series_id")
    p_obs.add_argument("--as-of", default=None, help="ISO-8601 UTC instant (default: now)")
    p_obs.add_argument("--limit", type=int, default=20)
    p_rev = sub.add_parser("revisions", help="every vintage of one reference period")
    p_rev.add_argument("series_id")
    p_rev.add_argument("period", help="reference period, YYYY-MM-DD")
    p_fc = sub.add_parser("forecast", help="run the forecasts and record today's vintage")
    p_fc.add_argument("--as-of", default=None, help="replay a past day (ISO-8601 UTC)")
    p_fcs = sub.add_parser("forecasts", help="every forecast made for one target period")
    p_fcs.add_argument("series_id")
    p_fcs.add_argument("period", help="target period, YYYY-MM-DD")
    p_an = sub.add_parser("analyze", help="macro dimension scores and the Gold / USDJPY views")
    p_an.add_argument("--as-of", default=None, help="build from data knowable at this instant")
    p_val = sub.add_parser("validate", help="score forecasts whose period has printed")
    p_val.add_argument("--as-of", default=None, help="score as at a past instant (ISO-8601)")
    p_rep = sub.add_parser("report", help="write today's daily Markdown report")
    p_rep.add_argument("--as-of", default=None, help="render as at a past instant (ISO-8601)")
    p_daily = sub.add_parser(
        "daily", help="the whole chain: migrate, collect, normalize, forecast, analyze, report"
    )
    p_daily.add_argument("--as-of", default=None, help="replay a past day (ISO-8601 UTC)")
    p_acc = sub.add_parser("accuracy", help="MAE / skill vs naive / directional / calibration")
    p_acc.add_argument("--series", default=None, help="limit to one target series_id")
    return parser.parse_args(argv)


def _dispatch(app: App, args: argparse.Namespace) -> int:
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
    if args.command == "normalize":
        return _cmd_normalize(app, args.series)
    if args.command == "series":
        return _cmd_series(app)
    if args.command == "observations":
        return _cmd_observations(app, args.series_id, args.as_of, args.limit)
    if args.command == "revisions":
        return _cmd_revisions(app, args.series_id, args.period)
    if args.command == "forecast":
        return _cmd_forecast(app, args.as_of)
    if args.command == "forecasts":
        return _cmd_forecasts(app, args.series_id, args.period)
    if args.command == "analyze":
        return _cmd_analyze(app, args.as_of)
    if args.command == "validate":
        return _cmd_validate(app, args.as_of)
    if args.command == "accuracy":
        return _cmd_accuracy(app, args.series)
    if args.command == "report":
        return _cmd_report(app, args.as_of)
    if args.command == "daily":
        return _cmd_daily(app, args.as_of)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(list(argv) if argv is not None else sys.argv[1:])
    try:
        return _dispatch(build_app(), args)
    except MiosError as exc:
        logger.error("fatal: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())

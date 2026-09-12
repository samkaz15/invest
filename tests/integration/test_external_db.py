"""Institutional forecasts, and the comparison they exist to make.

`forecast_errors` answers "did the drivers beat doing nothing?". That is a
low bar. What this covers is the question that decides whether the project
was worth building — did MIOS beat the number that was already public and
free on the same morning — and the three ways that comparison can quietly
become flattering instead of true:

* a backfill of a year of nowcasts read as though MIOS had held them all
  along,
* a MIOS forecast paired against a provider figure published later, when
  more was known,
* the two sides scored against different actuals or different baselines.

Each has a test here, and each would produce a good-looking number rather
than an error.
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mios.common.errors import MiosError
from mios.config.loader import load_config
from mios.ingestion.rawitem import RawItem
from mios.prediction.bridge import forecast_target
from mios.prediction.external import ExternalForecastRepo, ExternalIngestor
from mios.prediction.repo import ForecastRepo
from mios.series.repo import ObservationRepo, SeriesRepo
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources
from mios.validation.benchmark import BenchmarkReader, BenchmarkScorer
from mios.validation.scoring import Scorer

REPO = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("MIOS_TEST_DATABASE_URL", "postgresql://localhost/mios_test")

PROVIDER = "src_clevelandfed_nowcast"
TARGET = "ser_us_core_cpi_index"


@pytest.fixture(scope="module")
def db() -> Database:
    database = Database(TEST_DSN)
    if not database.ping():
        pytest.skip(f"test database unreachable: {TEST_DSN}")
    database.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    MigrationRunner(database, REPO / "db" / "migrations").apply_all()
    config = load_config(REPO / "config")
    sync_sources(database, config.sources)
    SeriesRepo(database).sync(config.series.series)
    return database


@pytest.fixture()
def clean(db: Database) -> Database:
    for table in (
        "external_forecast_errors",
        "external_forecasts",
        "forecast_errors",
        "predictions",
        "observations",
    ):
        db.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only")
        db.execute(f"DELETE FROM {table}")
        db.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only")
    return db


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class _MemoryStore:
    """Just enough raw store to hand the ingestor payloads."""

    def __init__(self, items: list[RawItem]) -> None:
        self._items = items

    def items(self, source_id: str) -> list[RawItem]:
        return [i for i in self._items if i.source_id == source_id]


def _payload(core: str, period: str = "2026-08-01") -> str:
    return f"Date,CPI,Core CPI\n{period},0.31,{core}\n"


def _item(core: str, retrieved: str, seq: int, period: str = "2026-08-01") -> RawItem:
    return RawItem(
        raw_item_id=f"raw_{seq:017x}",
        source_id=PROVIDER,
        retrieved_at=_at(retrieved),
        content_hash=f"{seq:064x}",
        content_type="text/csv",
        payload_text=_payload(core, period),
    )


def _ingest(db: Database, items: list[RawItem]) -> object:
    config = load_config(REPO / "config")
    return ExternalIngestor(
        _MemoryStore(items),  # type: ignore[arg-type]
        ExternalForecastRepo(db),
        config.external,
        {sid: spec.tier for sid, spec in config.sources.items()},
    ).run()


# ------------------------------------------------------------------ ingestion


def test_a_republished_unchanged_figure_does_not_become_a_new_vintage(clean: Database) -> None:
    """The file is republished daily whether or not the nowcast moved.

    A row per fetch would turn published_at into "when we last looked" and
    would later read as a forecaster changing their mind every single day.
    """
    # Two rows, because the payload carries both configured targets.
    report = _ingest(clean, [_item("0.28", "2026-09-01T12:00:00", 1)])
    assert report.written == 2  # type: ignore[attr-defined]

    again = _ingest(clean, [_item("0.28", "2026-09-02T12:00:00", 2)])
    assert again.written == 0  # type: ignore[attr-defined]
    assert again.unchanged == 2  # type: ignore[attr-defined] - two configured targets

    rows = clean.query(
        "SELECT * FROM external_forecasts WHERE target_series_id=%(t)s", {"t": TARGET}
    )
    assert len(rows) == 1


def test_a_moved_nowcast_is_a_second_row_not_an_edit(clean: Database) -> None:
    _ingest(clean, [_item("0.28", "2026-09-01T12:00:00", 1)])
    _ingest(clean, [_item("0.33", "2026-09-05T12:00:00", 2)])

    rows = clean.query(
        "SELECT * FROM external_forecasts WHERE target_series_id=%(t)s ORDER BY vintage_at",
        {"t": TARGET},
    )
    assert [r["point_value"] for r in rows] == [Decimal("0.0028"), Decimal("0.0033")]


def test_the_published_figure_is_kept_beside_the_converted_one(clean: Database) -> None:
    """A factor-of-a-hundred conversion bug is otherwise undetectable later.

    It would not raise. It would simply report the Cleveland Fed as wrong by
    two orders of magnitude, which reads as a finding rather than as a bug.
    """
    _ingest(clean, [_item("0.28", "2026-09-01T12:00:00", 1)])
    row = clean.query_one(
        "SELECT * FROM external_forecasts WHERE target_series_id=%(t)s", {"t": TARGET}
    )
    assert row is not None
    assert row["raw_value"] == Decimal("0.28")
    assert row["raw_unit"] == "percent_mom"
    assert row["point_value"] == Decimal("0.0028")
    assert row["source_url"].startswith("https://")


def test_a_stored_forecast_cannot_be_rewritten(clean: Database) -> None:
    """Enforced by the database, not by this module's good intentions."""
    _ingest(clean, [_item("0.28", "2026-09-01T12:00:00", 1)])
    with pytest.raises(MiosError):
        clean.execute("UPDATE external_forecasts SET point_value = 0.99")
    with pytest.raises(MiosError):
        clean.execute("DELETE FROM external_forecasts")


def test_a_backfill_is_not_credited_to_the_day_it_was_published(clean: Database) -> None:
    """The leak this table is shaped to prevent.

    Downloading a year of nowcast history today gives rows whose
    published_at is old. Reading them by published_at would let a backtest
    use forecasts MIOS had not yet fetched, and the resulting comparison
    would look excellent.
    """
    _ingest(clean, [_item("0.28", "2026-12-01T00:00:00", 1)])  # fetched in December
    repo = ExternalForecastRepo(clean)

    assert repo.as_of(TARGET, date(2026, 8, 1), _at("2026-09-01T00:00:00")) == []
    assert len(repo.as_of(TARGET, date(2026, 8, 1), _at("2026-12-02T00:00:00"))) == 1


# -------------------------------------------------------------------- scoring


def test_both_sides_are_scored_against_the_same_first_print(clean: Database) -> None:
    """Not the latest revision, and not a baseline stored on a different day.

    If the two scoring paths disagreed on either, every head-to-head figure
    would be an artefact of that disagreement rather than a finding.
    """
    observations = ObservationRepo(clean)
    config = load_config(REPO / "config")
    spec = config.series.by_id()[TARGET]

    # Eighteen months of history, knowable well before the forecast.
    history = [300.0 + 0.9 * i for i in range(18)]
    periods = [date(2025, m, 1) for m in range(1, 13)] + [date(2026, m, 1) for m in range(1, 7)]
    observations.write_vintage(
        spec,
        list(zip(periods, [Decimal(str(v)) for v in history], strict=True)),
        _at("2026-07-10T12:00:00"),
        "raw_00000000000000001",
    )

    # MIOS forecasts July, then the outside forecaster publishes for July.
    forecast = forecast_target(
        observations,
        config.forecast.by_id()[TARGET],
        _at("2026-07-15T00:00:00"),
        _at("2026-07-15T00:00:00"),
    )
    assert forecast is not None
    ForecastRepo(clean).save(forecast)
    _ingest(clean, [_item("0.30", "2026-07-16T12:00:00", 2, period="2026-07-01")])

    # July prints, then is revised upward a month later.
    observations.write_vintage(
        spec,
        [(date(2026, 7, 1), Decimal("316.5"))],
        _at("2026-08-12T12:30:00"),
        "raw_00000000000000003",
    )
    observations.write_vintage(
        spec,
        [(date(2026, 7, 1), Decimal("318.9"))],
        _at("2026-09-12T12:30:00"),
        "raw_00000000000000004",
    )

    now = _at("2026-10-01T00:00:00")
    Scorer(clean, observations, config.forecast.by_id()).run(now)
    BenchmarkScorer(clean, observations, ExternalForecastRepo(clean), config.forecast.by_id()).run(
        now
    )

    mine = clean.query_one("SELECT * FROM forecast_errors")
    theirs = clean.query_one("SELECT * FROM external_forecast_errors")
    assert mine is not None and theirs is not None
    # The first print, 316.5, not the 318.9 revision — for both.
    assert mine["actual"] == theirs["actual"]
    assert mine["actual_vintage_at"] == theirs["actual_vintage_at"]
    # Same naive baseline, so `skill` means the same thing in both tables.
    # Agreement to the sixth decimal is agreement in full: a stored forecast
    # rounds its baseline at six places, and the benchmark recomputes it in
    # float. Anything beyond that is below the precision either table keeps.
    assert mine["baseline_value"] == pytest.approx(theirs["baseline_value"], abs=1e-6)

    comparison = BenchmarkReader(clean).comparisons()
    assert len(comparison) == 1
    assert comparison[0].n == 1
    assert comparison[0].sufficient is False  # one period is not evidence


def test_a_provider_forecast_published_after_ours_is_never_the_one_compared(
    clean: Database,
) -> None:
    """Otherwise the comparison hands one side information the other lacked.

    Pairing MIOS's 30-days-out call against a nowcast published the morning
    of the release would not be a hard test failed — it would be a flattering
    number, in whichever direction, computed from two different questions.
    """
    observations = ObservationRepo(clean)
    repo = ExternalForecastRepo(clean)
    _ingest(clean, [_item("0.20", "2026-07-01T12:00:00", 1, period="2026-07-01")])
    _ingest(clean, [_item("0.45", "2026-07-20T12:00:00", 2, period="2026-07-01")])

    early = repo.as_of(TARGET, date(2026, 7, 1), _at("2026-07-10T00:00:00"))
    assert [r["point_value"] for r in early] == [Decimal("0.0020")]

    late = repo.as_of(TARGET, date(2026, 7, 1), _at("2026-07-25T00:00:00"))
    assert [r["point_value"] for r in late] == [Decimal("0.0045")]
    assert observations is not None

"""Vintage and as-of semantics, against a real PostgreSQL.

These are the tests the project exists for. Everything else can be rebuilt;
if these are wrong, every forecast the system ever scores is contaminated
by data it could not have had (CONSTITUTION.md Art.6).

Skipped when the database is unreachable so the unit suite runs anywhere;
CI provides PostgreSQL and fails the build if they skip.
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mios.config.loader import load_config
from mios.config.series import SeriesSpec
from mios.series.repo import ObservationRepo, SeriesRepo
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources

REPO = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("MIOS_TEST_DATABASE_URL", "postgresql://localhost/mios_test")

CPI = "ser_us_cpi_index"
AUGUST = date(2026, 8, 1)
JULY = date(2026, 7, 1)


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


@pytest.fixture(scope="module")
def spec() -> SeriesSpec:
    return load_config(REPO / "config").series.by_id()[CPI]


@pytest.fixture()
def repo(db: Database) -> ObservationRepo:
    db.execute("DELETE FROM normalize_state")
    # observations is append-only, so the trigger has to be stepped around
    # deliberately to give each test a clean slate. Doing it here, in one
    # visible place, is better than weakening the trigger.
    db.execute("ALTER TABLE observations DISABLE TRIGGER observations_append_only")
    db.execute("DELETE FROM observations")
    db.execute("ALTER TABLE observations ENABLE TRIGGER observations_append_only")
    return ObservationRepo(db)


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


# --------------------------------------------------------------- the trigger


def test_observations_cannot_be_updated_or_deleted(
    repo: ObservationRepo, spec: SeriesSpec, db: Database
) -> None:
    """History is protected by the database, not by good intentions."""
    repo.write_vintage(spec, [(AUGUST, Decimal("325.4"))], _at("2026-09-11"), "raw_x")
    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE observations SET value = 999 WHERE series_id = %(s)s", {"s": CPI})
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM observations WHERE series_id = %(s)s", {"s": CPI})


# ------------------------------------------------------------ write dedupe


def test_refetching_unchanged_data_writes_nothing(repo: ObservationRepo, spec: SeriesSpec) -> None:
    """Daily polling must not turn 400 periods of history into 400 rows a day.

    Without this, the revision count would measure how often we fetched
    rather than how often the agency restated its numbers.
    """
    points = [(JULY, Decimal("324.9")), (AUGUST, Decimal("325.4"))]
    first = repo.write_vintage(spec, points, _at("2026-09-11"), "raw_1")
    second = repo.write_vintage(spec, points, _at("2026-09-12"), "raw_2")

    assert (first.written, first.skipped) == (2, 0)
    assert (second.written, second.skipped) == (0, 2)
    assert len(repo.revisions(CPI, AUGUST)) == 1


def test_a_changed_value_is_recorded_as_a_new_vintage(
    repo: ObservationRepo, spec: SeriesSpec
) -> None:
    repo.write_vintage(spec, [(AUGUST, Decimal("325.4"))], _at("2026-09-11"), "raw_1")
    result = repo.write_vintage(spec, [(AUGUST, Decimal("325.6"))], _at("2026-10-13"), "raw_2")

    assert (result.written, result.revisions) == (1, 1)
    history = repo.revisions(CPI, AUGUST)
    assert [(h.revision_n, h.value) for h in history] == [
        (0, Decimal("325.4")),
        (1, Decimal("325.6")),
    ]


def test_reformatted_but_equal_values_are_not_revisions(
    repo: ObservationRepo, spec: SeriesSpec
) -> None:
    """3.20 and 3.2 are the same number.

    Providers reformat; comparing as text would manufacture a revision
    every time one did.
    """
    repo.write_vintage(spec, [(AUGUST, Decimal("325.40"))], _at("2026-09-11"), "raw_1")
    result = repo.write_vintage(spec, [(AUGUST, Decimal("325.4"))], _at("2026-09-12"), "raw_2")
    assert (result.written, result.skipped) == (0, 1)


def test_a_published_gap_is_stored_and_distinguished_from_absence(
    repo: ObservationRepo, spec: SeriesSpec
) -> None:
    repo.write_vintage(spec, [(AUGUST, None)], _at("2026-09-11"), "raw_1")
    rows = repo.as_of(CPI, _at("2026-09-30"))
    assert len(rows) == 1 and rows[0].value is None

    # ...and a later real figure supersedes the gap rather than colliding.
    result = repo.write_vintage(spec, [(AUGUST, Decimal("325.4"))], _at("2026-09-20"), "raw_2")
    assert result.written == 1
    assert repo.as_of(CPI, _at("2026-09-30"))[0].value == Decimal("325.4")


# ------------------------------------------------------------------- as-of


def test_as_of_hides_a_revision_that_had_not_happened_yet(
    repo: ObservationRepo, spec: SeriesSpec
) -> None:
    """The whole point of the schema, in one assertion.

    August CPI was first printed as 325.4 and restated to 325.6 in October.
    An analysis dated September must see 325.4, because that is what the
    market was trading on. A table that merged in place would show 325.6
    and every backtest built on it would be fiction.
    """
    repo.write_vintage(spec, [(AUGUST, Decimal("325.4"))], _at("2026-09-11"), "raw_1")
    repo.write_vintage(spec, [(AUGUST, Decimal("325.6"))], _at("2026-10-13"), "raw_2")

    september_view = repo.as_of(CPI, _at("2026-09-20"))
    october_view = repo.as_of(CPI, _at("2026-10-20"))

    assert [o.value for o in september_view] == [Decimal("325.4")]
    assert [o.value for o in october_view] == [Decimal("325.6")]


def test_as_of_before_first_publication_returns_nothing(
    repo: ObservationRepo, spec: SeriesSpec
) -> None:
    """August data is not knowable in August: it is published in September."""
    repo.write_vintage(spec, [(AUGUST, Decimal("325.4"))], _at("2026-09-11"), "raw_1")
    assert repo.as_of(CPI, _at("2026-09-01")) == []
    assert repo.latest_as_of(CPI, _at("2026-09-01")) is None


def test_as_of_returns_periods_oldest_first_and_latest_is_the_newest_period(
    repo: ObservationRepo, spec: SeriesSpec
) -> None:
    repo.write_vintage(
        spec,
        [(AUGUST, Decimal("325.4")), (JULY, Decimal("324.9"))],
        _at("2026-09-11"),
        "raw_1",
    )
    rows = repo.as_of(CPI, _at("2026-09-30"))
    assert [r.observation_date for r in rows] == [JULY, AUGUST]
    latest = repo.latest_as_of(CPI, _at("2026-09-30"))
    assert latest is not None and latest.observation_date == AUGUST


def test_as_of_window_filters_by_reference_period(repo: ObservationRepo, spec: SeriesSpec) -> None:
    repo.write_vintage(
        spec,
        [(JULY, Decimal("324.9")), (AUGUST, Decimal("325.4"))],
        _at("2026-09-11"),
        "raw_1",
    )
    rows = repo.as_of(CPI, _at("2026-09-30"), start=AUGUST)
    assert [r.observation_date for r in rows] == [AUGUST]


def test_coverage_reports_a_configured_series_with_no_data(
    repo: ObservationRepo, spec: SeriesSpec
) -> None:
    """A series that has never produced a row must be visible as a gap.

    Reporting it as a quiet zero is how a dead source stays dead for months.
    """
    repo.write_vintage(spec, [(AUGUST, Decimal("325.4"))], _at("2026-09-11"), "raw_1")
    rows = {r["series_id"]: r for r in repo.coverage()}
    assert rows[CPI]["vintages"] == 1
    empty = [sid for sid, r in rows.items() if r["vintages"] == 0]
    assert len(empty) > 1  # every other configured series, honestly reported


# --------------------------------------------------------- the normalizer


def test_normalizer_stamps_the_fetch_time_not_the_run_time(
    db: Database, repo: ObservationRepo
) -> None:
    """The BIOS bug this replaces, asserted so it cannot come back.

    The old normalizer wrote whatever payload it found as the *current*
    hour's value, so a source dead for three days still produced today's
    number (docs/REPOSITORY_AUDIT.md §14 L4). Here the vintage is the
    retrieval time carried by the raw item, so data fetched a week ago
    stays a week old no matter when normalization runs.
    """
    from mios.config.loader import load_config
    from mios.ingestion.rawitem import RawItem
    from mios.series.normalize import Normalizer

    fetched_at = _at("2026-09-11")
    payload = (REPO / "tests" / "fixtures" / "fred_cpiaucsl.json").read_text(encoding="utf-8")

    class OneItemStore:
        """Raw store holding a single stale payload."""

        def __init__(self, item: RawItem) -> None:
            self._item = item

        def seen(self, source_id: str, content_hash: str) -> bool:
            return False

        def put(self, item: RawItem) -> bool:
            return True

        def items(self, source_id: str):  # type: ignore[no-untyped-def]
            if source_id == self._item.source_id:
                yield self._item

        def latest(self, source_id: str) -> RawItem | None:
            return self._item if source_id == self._item.source_id else None

    item = RawItem(
        raw_item_id="raw_0123456789abcdef0",
        source_id="src_fred_cpiaucsl",
        retrieved_at=fetched_at,
        content_hash="deadbeef",
        content_type="application/json",
        payload_text=payload,
        url="https://api.stlouisfed.org/fred/series/observations",
    )
    config = load_config(REPO / "config")
    report = Normalizer(db, OneItemStore(item), config.series, repo).run(series_id=CPI)

    assert report.ok, report.failures
    assert report.written == 4  # three figures plus one published gap

    stored = repo.as_of(CPI, _at("2026-09-30"))
    assert {o.vintage_at for o in stored} == {fetched_at}
    # ...and therefore invisible to an analysis dated before the fetch.
    assert repo.as_of(CPI, _at("2026-09-10")) == []


def test_normalizer_reports_a_parse_failure_instead_of_an_empty_success(
    db: Database, repo: ObservationRepo
) -> None:
    """A provider that changed its response must fail the run, loudly."""
    from mios.config.loader import load_config
    from mios.ingestion.rawitem import RawItem
    from mios.series.normalize import Normalizer

    class OneItemStore:
        def __init__(self, item: RawItem) -> None:
            self._item = item

        def seen(self, source_id: str, content_hash: str) -> bool:
            return False

        def put(self, item: RawItem) -> bool:
            return True

        def items(self, source_id: str):  # type: ignore[no-untyped-def]
            if source_id == self._item.source_id:
                yield self._item

        def latest(self, source_id: str) -> RawItem | None:
            return self._item

    item = RawItem(
        raw_item_id="raw_0123456789abcdff0",
        source_id="src_fred_cpiaucsl",
        retrieved_at=_at("2026-09-11"),
        content_hash="cafebabe",
        content_type="application/json",
        payload_text='{"series": [], "note": "we restructured our API"}',
    )
    config = load_config(REPO / "config")
    report = Normalizer(db, OneItemStore(item), config.series, repo).run(series_id=CPI)

    assert not report.ok
    assert report.written == 0
    assert any("no 'observations' list" in f for f in report.failures)

"""Recording publications, and refusing to invent the ones nobody watched.

`releases` is the sheet a reader keeps notes beside, so the thing that
matters most is that every row in it is true. The failure this guards is not
a crash: it is a backfill quietly becoming nineteen releases, each stamped
with the moment MIOS happened to download it, asserting publication dates
that were never announced. It would look like a full year of history and
read as evidence.
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mios.config.loader import load_config
from mios.series.repo import ObservationRepo, SeriesRepo
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources
from mios.validation.releases import ReleaseBuilder

REPO = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("MIOS_TEST_DATABASE_URL", "postgresql://localhost/mios_test")
CPI = "ser_us_core_cpi_index"


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
def repo(db: Database) -> ObservationRepo:
    for table in ("releases", "observations"):
        db.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only")
        db.execute(f"DELETE FROM {table}")
        db.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only")
    return ObservationRepo(db)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def _builder(db: Database) -> ReleaseBuilder:
    config = load_config(REPO / "config")
    return ReleaseBuilder(db, ObservationRepo(db), config.series)


def _write(repo: ObservationRepo, points: list[tuple[date, str]], vintage: str, raw: str) -> None:
    spec = load_config(REPO / "config").series.by_id()[CPI]
    repo.write_vintage(spec, [(p, Decimal(v)) for p, v in points], _at(vintage), raw)


def _backfill(repo: ObservationRepo) -> None:
    """Six months arriving in one download, as a first collection does."""
    _write(
        repo,
        [(date(2026, m, 1), str(300 + m)) for m in range(1, 7)],
        "2026-07-10T12:30:00",
        "raw_00000000000000001",
    )


def test_a_backfill_produces_no_releases(db: Database, repo: ObservationRepo) -> None:
    """Six months landed at once. MIOS cannot say when any of them printed.

    Recording them would stamp each with the download time and assert a
    publication date nobody announced — and it would look like history.
    """
    _backfill(repo)
    report = _builder(db).run(_at("2026-07-11T00:00:00"), [CPI])
    assert report.written == 0
    assert report.unresolved == 6
    assert db.query("SELECT * FROM releases") == []


def test_a_print_that_lands_while_mios_is_watching_is_a_release(
    db: Database, repo: ObservationRepo
) -> None:
    _backfill(repo)
    _write(repo, [(date(2026, 7, 1), "307.5")], "2026-08-12T12:30:00", "raw_00000000000000002")

    report = _builder(db).run(_at("2026-08-13T00:00:00"), [CPI])
    assert report.written == 1

    [row] = db.query("SELECT * FROM releases")
    assert row["period"] == date(2026, 7, 1)
    # The release time is the print's own vintage, not the moment scoring ran.
    assert row["release_at"] == _at("2026-08-12T12:30:00")
    assert row["actual"] == Decimal("307.500")
    assert row["source_url"].endswith("CPILFESL")


def test_a_revision_to_the_prior_month_is_kept_as_two_numbers(
    db: Database, repo: ObservationRepo
) -> None:
    """`previous` is what the market was comparing against; `revised_previous`
    is what this release restated it to.

    The gap between them is frequently the real news of a release, and one
    column could not hold both (指示書 §14).
    """
    _backfill(repo)
    _write(
        repo,
        [(date(2026, 6, 1), "306.4"), (date(2026, 7, 1), "307.5")],
        "2026-08-12T12:30:00",
        "raw_00000000000000002",
    )

    _builder(db).run(_at("2026-08-13T00:00:00"), [CPI])
    [row] = db.query("SELECT * FROM releases WHERE period = '2026-07-01'")
    assert row["previous"] == Decimal("306.000")  # June, before this print
    assert row["revised_previous"] == Decimal("306.400")  # June, as restated by it
    assert row["previous"] != row["revised_previous"]


def test_recording_is_idempotent_and_cannot_be_rewritten(
    db: Database, repo: ObservationRepo
) -> None:
    """A release record that could be edited is not a record."""
    _backfill(repo)
    _write(repo, [(date(2026, 7, 1), "307.5")], "2026-08-12T12:30:00", "raw_00000000000000002")
    builder = _builder(db)
    builder.run(_at("2026-08-13T00:00:00"), [CPI])

    again = builder.run(_at("2026-08-14T00:00:00"), [CPI])
    assert again.written == 0
    assert again.already_recorded == 1
    assert len(db.query("SELECT * FROM releases")) == 1

    from mios.common.errors import MiosError

    with pytest.raises(MiosError):
        db.execute("UPDATE releases SET actual = 999")

"""Forecasts end to end: built from as-of data, stored once, never rewritten.

The behaviour under test is the project's stated success condition
(CONSTITUTION.md Art.2): that in six months someone can ask what MIOS
thought ten days before a release, and get an answer that was not quietly
edited afterwards.
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mios.config.forecast import DriverSpec, TargetSpec
from mios.config.loader import load_config
from mios.prediction.bridge import forecast_target
from mios.prediction.repo import ForecastRepo
from mios.series.repo import ObservationRepo, SeriesRepo
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources

REPO = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("MIOS_TEST_DATABASE_URL", "postgresql://localhost/mios_test")

TARGET = "ser_us_core_cpi_index"
DRIVER = "ser_us_cpi_shelter"


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
    for table in ("predictions", "observations"):
        db.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only")
        db.execute(f"DELETE FROM {table}")
        db.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only")
    return ObservationRepo(db)


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def _spec(**over: object) -> TargetSpec:
    base: dict[str, object] = {
        "series_id": TARGET,
        "label": "US core CPI",
        "frequency": "monthly",
        "transform": "pct_change",
        "unit_label": "pp",
        "baseline_window": 3,
        "max_adjustment": 0.0015,
        "drivers": [
            DriverSpec(
                series_id=DRIVER,
                label="Shelter",
                mode="elastic",
                weight=0.44,
                window=12,
                justification="test fixture standing in for the shelter basket share",
            )
        ],
    }
    base.update(over)
    return TargetSpec.model_validate(base)


def _load_months(
    repo: ObservationRepo, series_id: str, values: list[float], vintage: datetime
) -> None:
    """Write a monthly index starting 2025-01, all at one vintage."""
    config = load_config(REPO / "config")
    spec = config.series.by_id()[series_id]
    points = []
    for i, value in enumerate(values):
        year, month = 2025 + i // 12, i % 12 + 1
        points.append((date(year, month, 1), Decimal(str(value))))
    repo.write_vintage(spec, points, vintage, f"raw_{series_id}")


# ------------------------------------------------------------- the bridge


def test_a_forecast_is_the_baseline_plus_its_drivers(repo: ObservationRepo) -> None:
    """The arithmetic is replayable from the stored row, by hand.

    A steady 0.2%/month target gives a 0.002 baseline; a shelter component
    running hot against its own trend pushes the call above it by the
    driver's weight times that deviation, and nothing else.
    """
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    # Shelter matches the target for 29 months, then runs a tenth of a point
    # hot — enough to move the call, small enough not to hit the cap.
    hot_shelter = [100.0 * 1.002**i for i in range(29)] + [100.0 * 1.002**28 * 1.003]
    _load_months(repo, DRIVER, hot_shelter, _at("2027-08-01"))

    forecast = forecast_target(
        repo, _spec(), as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01")
    )
    assert forecast is not None
    assert forecast.baseline_value == pytest.approx(0.002, abs=1e-5)

    [driver] = forecast.drivers
    assert driver.contribution == pytest.approx(driver.value * 0.44)
    assert forecast.point_value == pytest.approx(
        forecast.baseline_value + driver.contribution, abs=1e-9
    )
    assert forecast.adjustment is not None and forecast.adjustment > 0


def test_the_adjustment_is_capped_and_the_cap_is_disclosed(repo: ObservationRepo) -> None:
    """One wild reading must not drag the call further than the method can
    justify — and when it is reined in, the forecast says so."""
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    wild = [100.0 * 1.002**i for i in range(29)] + [100.0 * 1.002**28 * 1.40]
    _load_months(repo, DRIVER, wild, _at("2027-08-01"))

    forecast = forecast_target(
        repo, _spec(), as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01")
    )
    assert forecast is not None
    assert forecast.adjustment == pytest.approx(0.0015)
    assert any("capped" in gap for gap in forecast.data_gaps)


def test_a_missing_driver_is_named_and_lowers_confidence(repo: ObservationRepo) -> None:
    """A forecast built on half its inputs must say so on its face."""
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    # Shelter is never loaded.

    forecast = forecast_target(
        repo, _spec(), as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01")
    )
    assert forecast is not None
    assert forecast.drivers == []
    assert any(DRIVER in gap for gap in forecast.data_gaps)
    assert forecast.confidence == 0.1
    # ...and with nothing to push it, the call falls back to the naive answer.
    assert forecast.point_value == pytest.approx(forecast.baseline_value)


def test_no_forecast_at_all_when_the_target_has_no_history(repo: ObservationRepo) -> None:
    """Better an absent row than a fabricated one in the table whose whole
    value is that it contains no fabricated rows."""
    assert (
        forecast_target(repo, _spec(), as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01"))
        is None
    )


def test_the_forecast_targets_the_period_after_the_latest_known_one(
    repo: ObservationRepo,
) -> None:
    _load_months(repo, TARGET, [100.0 * 1.002**i for i in range(20)], _at("2026-09-01"))
    forecast = forecast_target(
        repo, _spec(), as_of=_at("2026-10-01"), predicted_at=_at("2026-10-01")
    )
    assert forecast is not None
    assert forecast.target_period == date(2026, 9, 1)  # 20 months from 2025-01


def test_contradictory_drivers_are_surfaced_not_averaged_away(repo: ObservationRepo) -> None:
    """Disagreement among inputs is information about how far to trust the
    number, and a mean destroys it."""
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    hot = [100.0 * 1.002**i for i in range(29)] + [100.0 * 1.002**28 * 1.003]
    _load_months(repo, DRIVER, hot, _at("2027-08-01"))
    # Used cars cools while shelter runs hot — a real and common split.
    cold_id = "ser_us_cpi_used_cars"
    cold = [100.0 * 1.002**i for i in range(29)] + [100.0 * 1.002**28 * 0.999]
    _load_months(repo, cold_id, cold, _at("2027-08-01"))

    spec = _spec(
        drivers=[
            DriverSpec(
                series_id=DRIVER,
                label="Shelter",
                mode="elastic",
                weight=0.44,
                justification="test fixture standing in for the shelter basket share",
            ),
            DriverSpec(
                series_id=cold_id,
                label="Used cars",
                mode="elastic",
                weight=0.04,
                justification="test fixture standing in for the used car basket share",
            ),
        ]
    )
    forecast = forecast_target(repo, spec, as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01"))
    assert forecast is not None
    assert any("Used cars" in c for c in forecast.contradictions)


# ------------------------------------------------- as-of and the journal


def test_a_forecast_cannot_see_data_published_after_its_cutoff(
    repo: ObservationRepo,
) -> None:
    """The reason the whole vintage schema exists, reaching the forecast.

    The same call, replayed at an earlier cutoff, must be built only from
    what was knowable then — so a revision that landed later cannot change
    what the historical forecast said.
    """
    early = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, early, _at("2026-06-01"))
    _load_months(repo, DRIVER, early, _at("2026-06-01"))

    before_data = forecast_target(
        repo, _spec(), as_of=_at("2026-05-01"), predicted_at=_at("2026-05-01")
    )
    after_data = forecast_target(
        repo, _spec(), as_of=_at("2026-07-01"), predicted_at=_at("2026-07-01")
    )
    assert before_data is None  # nothing was knowable yet
    assert after_data is not None


def test_a_forecast_is_stored_once_and_a_rerun_leaves_it_alone(
    db: Database, repo: ObservationRepo
) -> None:
    """Re-running the daily job must be safe, and must never be an update."""
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    _load_months(repo, DRIVER, steady, _at("2027-08-01"))
    journal = ForecastRepo(db)

    forecast = forecast_target(
        repo, _spec(), as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01")
    )
    assert forecast is not None
    assert journal.save(forecast) is True
    assert journal.save(forecast) is False
    assert len(journal.vintages(TARGET, forecast.target_period)) == 1


def test_predictions_cannot_be_updated_or_deleted(db: Database, repo: ObservationRepo) -> None:
    """A single overwrite destroys the only thing this table is for."""
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    _load_months(repo, DRIVER, steady, _at("2027-08-01"))
    forecast = forecast_target(
        repo, _spec(), as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01")
    )
    assert forecast is not None
    ForecastRepo(db).save(forecast)

    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE predictions SET point_value = 9.99")
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM predictions")


def test_daily_forecasts_accumulate_as_a_vintage_trail(db: Database, repo: ObservationRepo) -> None:
    """The answer to "what did we think ten days before the release?".

    Each day's opinion is its own row, so the trail can be read forwards
    and the change from one day to the next is a subtraction, not a guess.
    """
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    _load_months(repo, DRIVER, steady, _at("2027-08-01"))
    journal = ForecastRepo(db)

    for day in ("2027-09-01", "2027-09-02", "2027-09-03"):
        forecast = forecast_target(repo, _spec(), as_of=_at(day), predicted_at=_at(day))
        assert forecast is not None
        assert journal.save(forecast) is True

    trail = journal.vintages(TARGET, date(2027, 7, 1))
    assert [row["predicted_at"].date().isoformat() for row in trail] == [
        "2027-09-01",
        "2027-09-02",
        "2027-09-03",
    ]

    previous = journal.previous(TARGET, date(2027, 7, 1), before=_at("2027-09-03"))
    assert previous is not None
    assert previous["predicted_at"].date().isoformat() == "2027-09-02"


def test_every_driver_is_stored_with_its_weight_and_contribution(
    db: Database, repo: ObservationRepo
) -> None:
    """ "Why is it this number?" must be answerable from the row alone."""
    steady = [100.0 * 1.002**i for i in range(30)]
    _load_months(repo, TARGET, steady, _at("2027-08-01"))
    hot = [100.0 * 1.002**i for i in range(29)] + [100.0 * 1.002**28 * 1.003]
    _load_months(repo, DRIVER, hot, _at("2027-08-01"))

    forecast = forecast_target(
        repo, _spec(), as_of=_at("2027-09-01"), predicted_at=_at("2027-09-01")
    )
    assert forecast is not None
    ForecastRepo(db).save(forecast)

    stored = ForecastRepo(db).get(forecast.forecast_id)
    assert stored is not None
    [driver] = stored["drivers"]
    assert {"series_id", "label", "value", "weight", "contribution", "rationale"} <= set(driver)
    replayed = float(stored["baseline_value"]) + sum(d["contribution"] for d in stored["drivers"])
    assert replayed == pytest.approx(float(stored["point_value"]), abs=1e-6)


def test_the_real_config_forecasts_run_against_an_empty_database(db: Database) -> None:
    """Every configured target must at least be *runnable*.

    With no observations they all decline to forecast, which is the correct
    answer — but a typo in a driver's series_id or a bad transform would
    raise here rather than three weeks into live collection.
    """
    config = load_config(REPO / "config")
    observations = ObservationRepo(db)
    for target in config.forecast.targets:
        forecast_target(
            observations, target, as_of=_at("2026-09-12"), predicted_at=_at("2026-09-12")
        )

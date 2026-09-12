"""Scoring forecasts, and refusing to overclaim from thin evidence.

This is the machinery behind CONSTITUTION.md Art.2's success condition, so
the tests are mostly about the two ways it could quietly lie: scoring
against a moving target, and reporting confident-looking accuracy from four
data points.
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mios.config.forecast import DriverSpec, TargetSpec
from mios.config.loader import load_config
from mios.prediction.models import Forecast
from mios.prediction.repo import ForecastRepo
from mios.series.repo import ObservationRepo, SeriesRepo
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources
from mios.validation.metrics import MIN_SAMPLE, MetricsReader
from mios.validation.scoring import Scorer, actual_change, first_print, score

REPO = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("MIOS_TEST_DATABASE_URL", "postgresql://localhost/mios_test")

TARGET = "ser_us_core_cpi_index"
JULY = date(2026, 7, 1)
AUGUST = date(2026, 8, 1)


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
    for table in ("forecast_errors", "predictions", "observations"):
        db.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only")
        db.execute(f"DELETE FROM {table}")
        db.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only")
    return ObservationRepo(db)


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def _spec() -> TargetSpec:
    return TargetSpec.model_validate(
        {
            "series_id": TARGET,
            "label": "US core CPI",
            "frequency": "monthly",
            "transform": "pct_change",
            "unit_label": "pp",
            "baseline_window": 3,
            "max_adjustment": 0.0015,
            "drivers": [
                DriverSpec(
                    series_id="ser_us_cpi_shelter",
                    label="Shelter",
                    mode="elastic",
                    weight=0.44,
                    justification="test fixture standing in for the shelter basket share",
                )
            ],
        }
    )


def _write(repo: ObservationRepo, period: date, value: str, vintage: str) -> None:
    spec = load_config(REPO / "config").series.by_id()[TARGET]
    repo.write_vintage(spec, [(period, Decimal(value))], _at(vintage), "raw_score")


def _forecast(
    point: float,
    baseline: float,
    predicted_at: str,
    period: date = AUGUST,
    upside: float | None = 0.7,
    suffix: str = "",
) -> Forecast:
    return Forecast(
        forecast_id=f"fc_{predicted_at}_core-cpi-{period.isoformat()}{suffix}",
        target_series_id=TARGET,
        target_period=period,
        predicted_at=_at(predicted_at),
        as_of=_at(predicted_at),
        point_value=point,
        baseline_value=baseline,
        upside_prob=upside,
        downside_prob=None if upside is None else round(1 - upside, 3),
        confidence=0.6,
        method_version="bridge/v1",
    )


# ------------------------------------------------------- the actual value


def test_the_actual_is_the_first_print_not_the_latest_revision(
    repo: ObservationRepo,
) -> None:
    """A forecaster predicts what will be printed.

    Scoring against a figure restated three months later marks them against
    a question nobody asked — and lets the target move under the scoreboard,
    so the same forecast would score differently depending on when the
    scoring job happened to run.
    """
    _write(repo, AUGUST, "325.412", "2026-09-11")
    _write(repo, AUGUST, "325.601", "2026-10-13")  # a later revision

    printed = first_print(repo, TARGET, AUGUST, as_of=_at("2027-01-01"))
    assert printed is not None
    value, vintage = printed
    assert value == pytest.approx(325.412)
    assert vintage == _at("2026-09-11")


def test_the_actual_change_uses_the_previous_period_as_it_then_stood(
    repo: ObservationRepo,
) -> None:
    """Both halves of the change come from the same moment.

    Using today's revised July against August's first print would mix
    vintages, and the answer would drift every time scoring re-ran.
    """
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    _write(repo, JULY, "999.000", "2026-11-01")  # a wild later restatement of July

    realised = actual_change(repo, _spec(), AUGUST, as_of=_at("2027-01-01"))
    assert realised is not None
    change, vintage = realised
    assert change == pytest.approx(325.0 / 324.0 - 1)
    assert vintage == _at("2026-09-11")


def test_no_score_before_the_period_has_printed(repo: ObservationRepo) -> None:
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    assert actual_change(repo, _spec(), AUGUST, as_of=_at("2026-09-01")) is None


# ------------------------------------------------------------- the score


def test_skill_is_positive_when_the_drivers_beat_doing_nothing() -> None:
    """The number the project lives or dies by."""
    actual = 0.0030
    scored = score(
        _forecast(point=0.0028, baseline=0.0020, predicted_at="2026-09-01").model_dump(
            mode="python"
        )
        | {"predicted_at": _at("2026-09-01")},
        actual,
        _at("2026-09-11"),
    )
    assert scored.error == pytest.approx(0.0002)
    assert scored.baseline_error == pytest.approx(0.0010)
    assert scored.skill > 0
    assert scored.direction_hit is True


def test_skill_is_negative_when_the_drivers_made_it_worse() -> None:
    scored = score(
        _forecast(point=0.0012, baseline=0.0020, predicted_at="2026-09-01").model_dump(
            mode="python"
        )
        | {"predicted_at": _at("2026-09-01")},
        0.0030,
        _at("2026-09-11"),
    )
    assert scored.skill < 0
    assert scored.direction_hit is False


def test_a_forecast_that_made_no_call_is_an_abstention_not_a_miss() -> None:
    """Counting a zero adjustment as a wrong direction would reward never
    leaving the baseline, which is the opposite of what this measures."""
    scored = score(
        _forecast(point=0.0020, baseline=0.0020, predicted_at="2026-09-01").model_dump(
            mode="python"
        )
        | {"predicted_at": _at("2026-09-01")},
        0.0030,
        _at("2026-09-11"),
    )
    assert scored.direction_hit is None


def test_days_ahead_records_how_far_out_the_call_was_made() -> None:
    """Accuracy at 30 days and at 1 day are different questions, and the
    daily vintages exist precisely so both can be asked."""
    scored = score(
        _forecast(point=0.0028, baseline=0.0020, predicted_at="2026-08-12").model_dump(
            mode="python"
        )
        | {"predicted_at": _at("2026-08-12")},
        0.0030,
        _at("2026-09-11"),
    )
    assert scored.days_ahead == 30


# ------------------------------------------------------------- the runner


def test_scoring_is_idempotent_and_never_rewrites_evidence(
    db: Database, repo: ObservationRepo
) -> None:
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    ForecastRepo(db).save(_forecast(0.0028, 0.0020, "2026-09-01"))

    scorer = Scorer(db, repo, {TARGET: _spec()})
    first = scorer.run(as_of=_at("2026-10-01"))
    second = scorer.run(as_of=_at("2026-10-01"))

    assert (first.scored, first.already_scored) == (1, 0)
    assert (second.scored, second.already_scored) == (0, 1)

    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE forecast_errors SET skill = 99")


def test_a_forecast_whose_period_has_not_printed_waits(db: Database, repo: ObservationRepo) -> None:
    _write(repo, JULY, "324.000", "2026-08-12")
    ForecastRepo(db).save(_forecast(0.0028, 0.0020, "2026-09-01"))

    report = Scorer(db, repo, {TARGET: _spec()}).run(as_of=_at("2026-09-20"))
    assert (report.scored, report.unresolved) == (0, 1)


# ------------------------------------------------------------- the metrics


def test_metrics_refuse_to_report_from_thin_evidence(db: Database, repo: ObservationRepo) -> None:
    """A directional accuracy of 100% from two forecasts is worse than no
    number, because it will be believed."""
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    for day in ("2026-09-01", "2026-09-02"):
        ForecastRepo(db).save(_forecast(0.0028, 0.0020, day))
    Scorer(db, repo, {TARGET: _spec()}).run(as_of=_at("2026-10-01"))

    [row] = MetricsReader(db).accuracy()
    assert row.n == 2
    assert row.sufficient is False
    assert row.mae is None and row.skill is None and row.beats_naive is None


def test_metrics_report_once_there_is_enough_to_report_on(
    db: Database, repo: ObservationRepo
) -> None:
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    # All ten calls made in early July, so all land in the same 31d+ band.
    # Horizon banding means ten forecasts spread across ten days would
    # report nothing, which is the intended behaviour rather than a flaw:
    # accuracy at 30 days out and at 1 day out are different questions and
    # must each earn their own sample.
    for i in range(MIN_SAMPLE):
        ForecastRepo(db).save(_forecast(0.0028, 0.0020, f"2026-07-{i + 1:02d}", suffix=f"-v{i}"))
    Scorer(db, repo, {TARGET: _spec()}).run(as_of=_at("2026-10-01"))

    rows = MetricsReader(db).accuracy()
    assert sum(r.n for r in rows) == MIN_SAMPLE
    reported = [r for r in rows if r.sufficient]
    assert [r.horizon for r in reported] == ["31d+"]
    for row in reported:
        assert row.mae is not None and row.mae >= 0
        assert row.baseline_mae is not None
        # 325/324 - 1 ≈ 0.00309, so the adjusted call was closer than naive.
        assert row.skill is not None and row.skill > 0
        assert row.beats_naive is True


def test_coverage_leads_with_how_much_evidence_exists(db: Database, repo: ObservationRepo) -> None:
    """The first thing a reader needs, and the one that stops the rest of
    the table from being over-read."""
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    ForecastRepo(db).save(_forecast(0.0028, 0.0020, "2026-09-01"))
    # A forecast for a period that has not printed — still waiting.
    ForecastRepo(db).save(
        _forecast(0.0031, 0.0020, "2026-09-02", period=date(2026, 9, 1), suffix="-sep")
    )
    Scorer(db, repo, {TARGET: _spec()}).run(as_of=_at("2026-10-01"))

    coverage = MetricsReader(db).coverage()
    assert coverage["scored"] == 1
    assert coverage["awaiting_actuals"] == 1


def test_calibration_compares_what_was_claimed_with_what_happened(
    db: Database, repo: ObservationRepo
) -> None:
    """The finding that makes stating a probability worth anything.

    Here every 70% call did land above baseline, so the band reads as
    under-confident rather than over — which is what the column is for.
    """
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    for i in range(MIN_SAMPLE):
        ForecastRepo(db).save(
            _forecast(0.0028, 0.0020, f"2026-09-{i + 1:02d}", upside=0.7, suffix=f"-c{i}")
        )
    Scorer(db, repo, {TARGET: _spec()}).run(as_of=_at("2026-10-01"))

    bins = {(b.lower, b.upper): b for b in MetricsReader(db).calibration()}
    bucket = bins[(0.6, 0.8)]
    assert bucket.n == MIN_SAMPLE
    assert bucket.stated == pytest.approx(0.7)
    assert bucket.realised == pytest.approx(1.0)
    assert bucket.overconfident is False


def test_forecasts_without_a_probability_are_left_out_of_calibration(
    db: Database, repo: ObservationRepo
) -> None:
    """A withheld probability is not a 50% one, and must not be scored as if
    it were."""
    _write(repo, JULY, "324.000", "2026-08-12")
    _write(repo, AUGUST, "325.000", "2026-09-11")
    ForecastRepo(db).save(_forecast(0.0028, 0.0020, "2026-09-01", upside=None))
    Scorer(db, repo, {TARGET: _spec()}).run(as_of=_at("2026-10-01"))

    assert all(b.n == 0 for b in MetricsReader(db).calibration())

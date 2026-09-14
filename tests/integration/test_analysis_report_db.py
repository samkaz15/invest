"""Macro scores, the two asset views, and the report that formats them.

Two properties matter most here and neither is about arithmetic. A score
must record what it structurally cannot see, so a reader does not mistake
the model's silence for absence. And the report must format stored rows and
nothing else — the moment it computes a figure of its own, that figure
cannot be reconciled with the database.
"""

import os
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from mios.analysis.macro import NEUTRAL_BAND, asset_view, score_dimension
from mios.analysis.repo import MacroScoreRepo
from mios.config.analysis import AssetViewSpec, DimensionSpec, SignalSpec, ViewLink
from mios.config.loader import load_config
from mios.reports.daily import DailyReport
from mios.series.repo import ObservationRepo, SeriesRepo
from mios.storage.db import Database
from mios.storage.migrate import MigrationRunner
from mios.storage.sync import sync_sources

REPO = Path(__file__).resolve().parents[2]
TEST_DSN = os.environ.get("MIOS_TEST_DATABASE_URL", "postgresql://localhost/mios_test")

VIX = "ser_us_vix"
UST2 = "ser_us_treasury_2y"


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
    for table in ("macro_scores", "forecast_errors", "predictions", "observations"):
        db.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only")
        db.execute(f"DELETE FROM {table}")
        db.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only")
    return ObservationRepo(db)


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def _load_daily(repo: ObservationRepo, series_id: str, values: list[float], vintage: str) -> None:
    spec = load_config(REPO / "config").series.by_id()[series_id]
    start = date(2026, 1, 1)
    points = [(start + timedelta(days=i), Decimal(str(v))) for i, v in enumerate(values)]
    repo.write_vintage(spec, points, _at(vintage), f"raw_{series_id}")


def _wobbling(base: float, n: int, spike: float) -> list[float]:
    """History with real spread, then a final outlier.

    A flat history has no scale to be unusual against, so the z-score
    correctly declines to read it — which makes a constant fixture test
    nothing. These values wobble the way a real series does.
    """
    history = [base + (0.4 if i % 2 else -0.4) + (0.1 * (i % 5)) for i in range(n)]
    return [*history, spike]


def _dimension(**over: object) -> DimensionSpec:
    base: dict[str, object] = {
        "dimension": "risk",
        "label": "Risk appetite",
        "stance_words": ("risk-off", "calm", "risk-on"),
        "signals": [
            SignalSpec(series_id=VIX, label="VIX", measure="level_z", weight=12.0, min_history=12)
        ],
        "blind_spots": ["Credit spreads are not collected."],
    }
    base.update(over)
    return DimensionSpec.model_validate(base)


# ------------------------------------------------------------- dimensions


def test_a_dimension_score_is_the_sum_of_its_signals(repo: ObservationRepo) -> None:
    """Replayable by hand from the stored signals, like every other score."""
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    score = score_dimension(repo, _dimension(), _at("2026-03-02"))

    assert score.signals, "a series with 21 points must produce a signal"
    assert score.score == pytest.approx(sum(s.points for s in score.signals))
    assert score.score > 0  # an elevated VIX is a positive risk reading
    assert score.stance == "risk-off"


def test_a_missing_series_becomes_a_named_gap_not_a_zero(repo: ObservationRepo) -> None:
    """A dimension built on nothing must not read as "neutral"."""
    score = score_dimension(repo, _dimension(), _at("2026-03-02"))
    assert score.signals == []
    assert any(VIX in gap for gap in score.data_gaps)
    assert score.confidence == 0.1
    assert score.score == 0


def test_thin_history_is_a_gap_rather_than_a_reading(repo: ObservationRepo) -> None:
    _load_daily(repo, VIX, [16.0, 17.0, 18.0], "2026-03-01")
    score = score_dimension(repo, _dimension(), _at("2026-03-02"))
    assert score.signals == []
    assert any("history n=3" in gap for gap in score.data_gaps)


def test_every_score_carries_what_it_cannot_see(repo: ObservationRepo) -> None:
    """The field exists because a reader not told will read silence as
    absence. The config schema refuses an empty list; this checks it survives
    into the stored score."""
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    score = score_dimension(repo, _dimension(), _at("2026-03-02"))
    assert score.blind_spots == ["Credit spreads are not collected."]


def test_a_score_near_zero_reports_balance_not_a_list_of_contradictions(
    repo: ObservationRepo,
) -> None:
    """When the net is ~0, everything disagrees with something.

    Listing three contradictions there is technically true and useless; the
    honest summary is that the inputs are split.
    """
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    _load_daily(repo, UST2, _wobbling(3.5, 20, 4.5), "2026-03-01")
    spec = _dimension(
        signals=[
            SignalSpec(series_id=VIX, label="VIX", measure="level_z", weight=12.0),
            SignalSpec(series_id=UST2, label="UST 2Y", measure="level_z", weight=-12.0),
        ]
    )
    score = score_dimension(repo, spec, _at("2026-03-02"))
    assert abs(score.score) <= NEUTRAL_BAND
    assert len(score.contradictions) == 1
    assert "拮抗" in score.contradictions[0]


# ------------------------------------------------------------ asset views


def test_an_asset_view_is_built_from_dimensions_not_from_raw_series_again(
    repo: ObservationRepo,
) -> None:
    """Reading the same yields twice under two names would double-count them
    and make the view look better supported than it is."""
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    risk = score_dimension(repo, _dimension(), _at("2026-03-02"))

    spec = AssetViewSpec.model_validate(
        {
            "view_id": "gold_bias",
            "asset_id": "ent_asset_xauusd",
            "label": "Gold macro bias",
            "stance_words": ("supportive", "neutral", "unsupportive"),
            "links": [
                ViewLink(
                    dimension="risk",
                    weight=-1.0,
                    rationale="risk-off conditions support gold, so the sign is inverted",
                )
            ],
            "blind_spots": ["Central-bank buying appears in no yield series."],
        }
    )
    view = asset_view(spec, {"risk": risk}, _at("2026-03-02"))

    [signal] = view.signals
    assert signal.value == pytest.approx(risk.score)
    assert view.score == pytest.approx(signal.points)
    # risk-off scored positive, and the link inverts it: supportive for gold.
    assert view.score < 0 or risk.score < 0


def test_a_view_missing_a_dimension_says_so_and_loses_confidence(
    repo: ObservationRepo,
) -> None:
    """USDJPY without the BOJ side is half a view, and must read as one."""
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    risk = score_dimension(repo, _dimension(), _at("2026-03-02"))
    empty_boj = score_dimension(
        repo,
        _dimension(
            dimension="boj",
            label="BOJ",
            signals=[
                SignalSpec(
                    series_id="ser_jp_jgb_10y", label="JGB 10Y", measure="change_z", weight=12.0
                )
            ],
            blind_spots=["Japanese CPI is not collected."],
        ),
        _at("2026-03-02"),
    )
    spec = AssetViewSpec.model_validate(
        {
            "view_id": "usdjpy_bias",
            "asset_id": "ent_asset_usdjpy",
            "label": "USDJPY macro bias",
            "stance_words": ("higher", "neutral", "lower"),
            "links": [
                ViewLink(
                    dimension="risk", weight=0.5, rationale="the yen bids in a flight to safety"
                ),
                ViewLink(
                    dimension="boj", weight=-0.5, rationale="a hawkish BOJ narrows the differential"
                ),
            ],
            "blind_spots": ["MOF intervention is not observable here."],
        }
    )
    view = asset_view(spec, {"risk": risk, "boj": empty_boj}, _at("2026-03-02"))

    assert any("boj" in gap for gap in view.data_gaps)
    assert len(view.signals) == 1
    assert view.confidence < risk.confidence


# ------------------------------------------------------------- persistence


def test_scores_are_append_only_and_a_rerun_is_a_no_op(db: Database, repo: ObservationRepo) -> None:
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    score = score_dimension(repo, _dimension(), _at("2026-03-02"))
    store = MacroScoreRepo(db)

    assert store.save(score) is True
    assert store.save(score) is False
    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE macro_scores SET score = 99")


def test_a_later_score_does_not_overwrite_an_earlier_one(
    db: Database, repo: ObservationRepo
) -> None:
    """The BIOS table upserted on (asset, dimension, as_of), so recomputing
    erased what the system had thought (audit §14 L3)."""
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    store = MacroScoreRepo(db)
    store.save(score_dimension(repo, _dimension(), _at("2026-03-02")))
    store.save(score_dimension(repo, _dimension(), _at("2026-03-03")))

    previous = store.previous("risk", before=_at("2026-03-03"))
    assert previous is not None
    assert previous["as_of"] == _at("2026-03-02")


# ---------------------------------------------------------------- report


def test_the_report_renders_on_an_empty_database(db: Database, repo: ObservationRepo) -> None:
    """Day one has to produce a readable file that says it has nothing.

    A report that crashes without data is a report nobody can schedule.
    """
    text = DailyReport(db, load_config(REPO / "config")).render(_at("2026-03-02"))
    assert text.startswith("# Daily Macro Report — 2026-03-02")
    assert "本日述べられることはまだない" in text
    assert "Data Quality / Missing Data" in text
    assert "Not Yet Implemented" in text


def test_the_report_names_what_is_not_implemented_rather_than_leaving_it_blank(
    db: Database, repo: ObservationRepo
) -> None:
    """An empty section reads as "nothing happened"; a named gap reads as
    "we do not collect this yet", and only one of those is true.

    The list this checks changes as gaps get filled — the calendar, the
    consensus and the headline list were all on it and are now sections of
    their own. What must not change is that whatever is still missing is
    written down on the page rather than silently absent.
    """
    text = DailyReport(db, load_config(REPO / "config")).render(_at("2026-03-02"))
    for missing in (
        # Collected, but not classified or summarised: the one place an LLM
        # will ever be used, and it needs a key this project does not have.
        "ニュースの分類・要約",
        # No public feed exists, so there is no collection path at all.
        "Reuters / Bloomberg",
        # e-Stat needs an API key and a reader of its own.
        "日本の CPI・賃金",
        # Monthly NFP consensus is a commercial product (ADR-012).
        "雇用統計のコンセンサス",
    ):
        assert missing in text, f"the report must still name this gap: {missing}"


def test_the_sections_that_were_gaps_are_now_sections(db: Database, repo: ObservationRepo) -> None:
    """They render on an empty database, saying they have no data yet.

    A report that crashes without data is a report nobody can schedule, and
    these three are exactly the ones that spend their first days empty.
    """
    text = DailyReport(db, load_config(REPO / "config")).render(_at("2026-03-02"))
    assert "## 本日の発表 / Economic Calendar" in text
    assert "## Headlines" in text
    assert "## Consensus / Institutional Forecasts" in text
    assert "発表予定がまだ1件も取得できていません" in text
    assert "ニュースはまだ1件も取得できていません" in text


def test_the_report_shows_stored_scores_and_their_blind_spots(
    db: Database, repo: ObservationRepo
) -> None:
    _load_daily(repo, VIX, _wobbling(16.0, 20, 30.0), "2026-03-01")
    config = load_config(REPO / "config")
    scores = {
        spec.dimension: score_dimension(repo, spec, _at("2026-03-02"))
        for spec in config.analysis.dimensions
    }
    store = MacroScoreRepo(db)
    for score in scores.values():
        store.save(score)
    for view in config.analysis.views:
        store.save(asset_view(view, scores, _at("2026-03-02")))

    text = DailyReport(db, config).render(_at("2026-03-02"))
    assert "Gold macro bias" in text
    assert "Central-bank gold buying" in text  # a blind spot, on the page
    assert "MOF intervention" in text


def test_the_report_reports_series_with_no_data_as_missing(
    db: Database, repo: ObservationRepo
) -> None:
    text = DailyReport(db, load_config(REPO / "config")).render(_at("2026-03-02"))
    assert "**未取得**" in text
    assert re.search(r"データ未取得: \d+ 系列", text)


def test_the_report_computes_no_numbers_of_its_own(db: Database) -> None:
    """The restriction that keeps it reconcilable with the database.

    Importing a scorer or a forecaster here would mean the report could
    disagree with the stored rows, and then neither would be trustworthy.
    """
    source = (REPO / "src" / "mios" / "reports" / "daily.py").read_text(encoding="utf-8")
    for forbidden in ("score_dimension", "asset_view", "forecast_target", "Scorer"):
        assert forbidden not in source, (
            f"reports/daily.py must format stored rows, not call {forbidden}"
        )

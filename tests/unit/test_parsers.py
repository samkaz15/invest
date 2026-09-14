"""Payload parser tests.

Most of these assert the *failure* behaviour rather than the happy path.
That is the point: the dangerous outcome for a data pipeline is not a
crash, it is a parser that returns an empty list when a provider changes
its response, because every layer above reads that as "nothing new today"
(docs/REPOSITORY_AUDIT.md §15, CONSTITUTION.md Art.4-4).

The fixtures under tests/fixtures/ are recorded payload shapes. They stand
in for a network this environment cannot reach; the shapes themselves are
confirmed against live responses in CI.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from mios.config.series import SeriesSpec
from mios.series.parsers import (
    ParseError,
    fred_json,
    get_parser,
    treasury_csv,
    twelvedata_json,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _spec(series_id: str, provider_code: str, parser: str, **over: object) -> SeriesSpec:
    base: dict[str, object] = {
        "series_id": series_id,
        "name": "test series",
        "country": "US",
        "category": "inflation",
        "unit": "index",
        "frequency": "monthly",
        "source_id": "src_fred_cpiaucsl",
        "provider_code": provider_code,
        "parser": parser,
        "revisable": True,
        "seasonal_adjustment": "sa",
    }
    base.update(over)
    return SeriesSpec.model_validate(base)


# ------------------------------------------------------------------ FRED


def test_fred_reads_observations_newest_first() -> None:
    spec = _spec("ser_us_cpi_index", "CPIAUCSL", "fred_json")
    points = fred_json((FIXTURES / "fred_cpiaucsl.json").read_text(encoding="utf-8"), spec)
    assert len(points) == 4
    assert points[0].observation_date.isoformat() == "2026-08-01"
    assert points[0].value == Decimal("325.412")


def test_fred_dot_is_a_published_gap_not_a_dropped_row() -> None:
    """FRED writes "." when it has no figure for a period.

    Preserved as a null value rather than skipped: "the agency published
    nothing for May" and "we never fetched May" are different facts, and
    only the row distinguishes them.
    """
    spec = _spec("ser_us_cpi_index", "CPIAUCSL", "fred_json")
    points = fred_json((FIXTURES / "fred_cpiaucsl.json").read_text(encoding="utf-8"), spec)
    may = next(p for p in points if p.observation_date.isoformat() == "2026-05-01")
    assert may.value is None


def test_fred_api_error_is_not_an_empty_result() -> None:
    spec = _spec("ser_us_cpi_index", "CPIAUCSL", "fred_json")
    payload = (
        '{"error_code": 400, "error_message": "Bad Request. '
        'The value for variable api_key is not registered."}'
    )
    with pytest.raises(ParseError, match="not registered"):
        fred_json(payload, spec)


def test_fred_missing_observations_key_raises() -> None:
    spec = _spec("ser_us_cpi_index", "CPIAUCSL", "fred_json")
    with pytest.raises(ParseError, match="no 'observations' list"):
        fred_json('{"count": 0}', spec)


def test_fred_non_numeric_value_raises_rather_than_coercing() -> None:
    spec = _spec("ser_us_cpi_index", "CPIAUCSL", "fred_json")
    payload = '{"observations": [{"date": "2026-08-01", "value": "n/a"}]}'
    with pytest.raises(ParseError, match="not a number"):
        fred_json(payload, spec)


def test_fred_html_error_page_raises() -> None:
    spec = _spec("ser_us_cpi_index", "CPIAUCSL", "fred_json")
    with pytest.raises(ParseError, match="not JSON"):
        fred_json("<html><body>503 Service Unavailable</body></html>", spec)


# -------------------------------------------------------------- Treasury


def test_treasury_csv_picks_its_own_column() -> None:
    """One CSV holds the whole curve; provider_code selects the tenor."""
    csv_text = (FIXTURES / "treasury_curve.csv").read_text(encoding="utf-8")
    two_year = treasury_csv(csv_text, _spec("ser_us_treasury_curve_2y", "2 Yr", "treasury_csv"))
    ten_year = treasury_csv(csv_text, _spec("ser_us_treasury_curve_10y", "10 Yr", "treasury_csv"))
    assert two_year[0].observation_date.isoformat() == "2026-09-11"
    assert two_year[0].value == Decimal("3.79")
    assert ten_year[0].value == Decimal("4.08")


def test_treasury_csv_blank_cell_is_a_null_value() -> None:
    csv_text = (FIXTURES / "treasury_curve.csv").read_text(encoding="utf-8")
    points = treasury_csv(csv_text, _spec("ser_us_treasury_curve_20y", "20 Yr", "treasury_csv"))
    missing = next(p for p in points if p.observation_date.isoformat() == "2026-09-09")
    assert missing.value is None


def test_treasury_csv_renamed_column_raises_with_the_headers_it_found() -> None:
    """A silently renamed column is the realistic provider change.

    The error carries the actual headers so the fix is one glance rather
    than one debugging session.
    """
    csv_text = (FIXTURES / "treasury_curve.csv").read_text(encoding="utf-8")
    spec = _spec("ser_us_treasury_curve_2y", "2 Year", "treasury_csv")
    with pytest.raises(ParseError, match=r"not in Treasury CSV.*2 Yr"):
        treasury_csv(csv_text, spec)


def test_treasury_csv_with_no_data_rows_raises() -> None:
    spec = _spec("ser_us_treasury_curve_2y", "2 Yr", "treasury_csv")
    with pytest.raises(ParseError, match="no data rows"):
        treasury_csv('Date,"2 Yr"\n', spec)


def test_treasury_csv_rejects_a_date_it_cannot_read() -> None:
    spec = _spec("ser_us_treasury_curve_2y", "2 Yr", "treasury_csv")
    with pytest.raises(ParseError, match="MM/DD/YYYY"):
        treasury_csv('Date,"2 Yr"\n2026-09-11,3.79\n', spec)


# ------------------------------------------------------------ Twelve Data


def test_twelvedata_reads_daily_closes() -> None:
    spec = _spec(
        "ser_xauusd",
        "XAU/USD",
        "twelvedata_json",
        category="commodity",
        unit="level",
        frequency="daily",
        revisable=False,
        seasonal_adjustment="not_applicable",
        source_id="src_twelvedata_xauusd",
    )
    points = twelvedata_json(
        (FIXTURES / "twelvedata_xauusd.json").read_text(encoding="utf-8"), spec
    )
    assert points[0].observation_date.isoformat() == "2026-09-11"
    assert points[0].value == Decimal("2412.30")


def test_twelvedata_rate_limit_is_a_failure_not_an_empty_day() -> None:
    """The vendor returns HTTP 200 with an error body when credits run out.

    Treating that as "no data today" would quietly thin the price history
    exactly when the system is being polled hardest.
    """
    spec = _spec(
        "ser_xauusd",
        "XAU/USD",
        "twelvedata_json",
        category="commodity",
        unit="level",
        frequency="daily",
        revisable=False,
        seasonal_adjustment="not_applicable",
        source_id="src_twelvedata_xauusd",
    )
    payload = (FIXTURES / "twelvedata_rate_limited.json").read_text(encoding="utf-8")
    with pytest.raises(ParseError, match="429"):
        twelvedata_json(payload, spec)


# -------------------------------------------------------------- registry


def test_unknown_parser_name_raises() -> None:
    with pytest.raises(ParseError, match="unknown parser"):
        get_parser("bloomberg_terminal")


def test_every_configured_parser_exists() -> None:
    """config/series.yaml can only name parsers that are implemented."""
    from mios.config.loader import load_config

    root = load_config(Path(__file__).resolve().parents[2] / "config")
    for spec in root.series.series:
        assert get_parser(spec.parser) is not None


# ----------------------------------------------------------------- ALFRED


def test_alfred_uses_the_publication_date_as_the_vintage() -> None:
    """The difference between "when it was published" and "when we polled".

    A plain FRED pull can only say when MIOS saw a number. ALFRED says when
    the agency made it public, which is what a backtest of a period MIOS
    was not yet running for actually needs.
    """
    from mios.series.parsers import alfred_json

    spec = _spec("ser_us_cpi_index_vintage", "CPIAUCSL", "alfred_json")
    points = alfred_json((FIXTURES / "alfred_cpiaucsl.json").read_text(encoding="utf-8"), spec)

    august = [p for p in points if p.observation_date.isoformat() == "2026-08-01"]
    assert [(p.vintage_at.isoformat() if p.vintage_at else None, p.value) for p in august] == [
        ("2026-09-11T00:00:00+00:00", Decimal("325.412")),
        ("2026-10-13T00:00:00+00:00", Decimal("325.601")),
    ]


def test_alfred_carries_several_vintages_of_one_period() -> None:
    from mios.series.parsers import alfred_json

    spec = _spec("ser_us_cpi_index_vintage", "CPIAUCSL", "alfred_json")
    points = alfred_json((FIXTURES / "alfred_cpiaucsl.json").read_text(encoding="utf-8"), spec)
    july = [p for p in points if p.observation_date.isoformat() == "2026-07-01"]
    assert len(july) == 2
    assert [p.value for p in july] == [Decimal("324.900"), Decimal("324.988")]


def test_alfred_row_without_realtime_start_raises() -> None:
    """Without a realtime_start there is no vintage, and inventing one is
    fabricating provenance."""
    from mios.series.parsers import alfred_json

    spec = _spec("ser_us_cpi_index_vintage", "CPIAUCSL", "alfred_json")
    payload = '{"observations": [{"date": "2026-08-01", "value": "325.4"}]}'
    with pytest.raises(ParseError, match="realtime_start"):
        alfred_json(payload, spec)


# -------------------------------------------------------------- MOF (JGB)


def _jgb_spec(tenor: str) -> SeriesSpec:
    return _spec(
        "ser_jp_jgb_10y",
        tenor,
        "mof_jgb_csv",
        country="JP",
        category="rates",
        unit="percent",
        frequency="daily",
        revisable=False,
        seasonal_adjustment="not_applicable",
        source_id="src_mof_jgb_yields",
    )


def test_mof_reads_japanese_tenor_columns_and_era_dates() -> None:
    """Reiwa 8 is 2026; the tenor headers are Japanese."""
    from mios.series.parsers import mof_jgb_csv

    csv_text = (FIXTURES / "mof_jgb.csv").read_text(encoding="utf-8")
    points = mof_jgb_csv(csv_text, _jgb_spec("10年"))
    assert points[-1].observation_date.isoformat() == "2026-09-11"
    assert points[-1].value == Decimal("1.634")


def test_mof_dash_is_a_published_gap() -> None:
    from mios.series.parsers import mof_jgb_csv

    csv_text = (FIXTURES / "mof_jgb.csv").read_text(encoding="utf-8")
    points = mof_jgb_csv(csv_text, _jgb_spec("40年"))
    assert points[-1].value is None


def test_mof_unknown_tenor_raises() -> None:
    from mios.series.parsers import mof_jgb_csv

    csv_text = (FIXTURES / "mof_jgb.csv").read_text(encoding="utf-8")
    with pytest.raises(ParseError, match="not found in MOF CSV"):
        mof_jgb_csv(csv_text, _jgb_spec("15年"))


def test_mof_rejects_an_era_it_does_not_know() -> None:
    """A future era change must fail, not silently produce dates decades off."""
    from mios.series.parsers import mof_jgb_csv

    with pytest.raises(ParseError, match="date"):
        mof_jgb_csv("基準日,10年\nH31.4.30,0.5\n", _jgb_spec("10年"))

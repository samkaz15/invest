"""Reading an outside forecaster's file.

The failure this reader is built around is not a crash. It is a renamed
column: the fetch returns HTTP 200, the CSV parses fine, and the reader
quietly finds nothing — which every layer above reads as "no new forecast
today", indefinitely. So most of what is tested here is the refusal to
return an empty list, and the quality of the message when it refuses.
"""

from decimal import Decimal

import pytest

from mios.config.external import ExternalTargetSpec, ProviderSpec
from mios.prediction.external import ExternalParseError, clevelandfed_nowcast_csv

CSV = """Date,CPI,Core CPI,PCE
2026-08-01,0.31,0.28,0.22
2026-09-01,0.24,0.26,0.19
2026-10-01,,,
"""


def _target(**over: object) -> ExternalTargetSpec:
    base: dict[str, object] = {
        "target_series_id": "ser_us_core_cpi_index",
        "provider_code": "Core CPI",
        "raw_unit": "percent_mom",
        "scale": 0.01,
    }
    base.update(over)
    return ExternalTargetSpec.model_validate(base)


def _provider(**over: object) -> ProviderSpec:
    base: dict[str, object] = {
        "provider_id": "src_clevelandfed_nowcast",
        "label": "Cleveland Fed",
        "parser": "clevelandfed_nowcast_csv",
        "source_url": "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting",
        "method": "A dynamic factor nowcast published daily.",
        "targets": [_target()],
    }
    base.update(over)
    return ProviderSpec.model_validate(base)


def test_it_reads_the_configured_column_and_nothing_else() -> None:
    points = clevelandfed_nowcast_csv(CSV, _provider(), _target())
    assert [(p.target_period.isoformat(), p.raw_value) for p in points] == [
        ("2026-08-01", Decimal("0.28")),
        ("2026-09-01", Decimal("0.26")),
    ]


def test_a_blank_cell_is_a_month_not_yet_nowcast_rather_than_an_error() -> None:
    """October is in the file with no figure. That is a real state."""
    points = clevelandfed_nowcast_csv(CSV, _provider(), _target())
    assert all(p.target_period.month != 10 for p in points)


def test_a_renamed_column_names_every_column_actually_present() -> None:
    """The whole point of failing loudly is that the fix is then one line.

    A message saying only "not found" leaves the reader to go and open the
    provider's file by hand; this one puts the answer in the CI log.
    """
    with pytest.raises(ExternalParseError) as caught:
        clevelandfed_nowcast_csv(CSV, _provider(), _target(provider_code="Core_CPI"))
    message = str(caught.value)
    assert "'Core_CPI'" in message
    assert "'Core CPI'" in message and "'PCE'" in message


def test_a_column_that_exists_but_is_entirely_empty_is_a_failure() -> None:
    """Not "no data today": a column of blanks means the id moved.

    Returning an empty list here would look identical to a quiet month, and
    nothing downstream could tell the difference.
    """
    empty = "Date,CPI,Core CPI\n2026-08-01,0.31,\n2026-09-01,0.24,\n"
    with pytest.raises(ExternalParseError, match="none carried a usable value"):
        clevelandfed_nowcast_csv(empty, _provider(), _target())


def test_a_file_with_no_date_column_fails_rather_than_inventing_periods() -> None:
    with pytest.raises(ExternalParseError, match="no date column"):
        clevelandfed_nowcast_csv("CPI,Core CPI\n0.31,0.28\n", _provider(), _target())


def test_an_html_error_page_does_not_parse_as_a_forecast() -> None:
    """Providers answer outages with HTML and a 200 more often than with a 500."""
    with pytest.raises(ExternalParseError):
        clevelandfed_nowcast_csv("<html><body>503</body></html>", _provider(), _target())


@pytest.mark.parametrize("spelling", ["2026-08-01", "2026-08", "08/15/2026", "Aug 2026"])
def test_the_month_is_read_from_the_spellings_a_forecast_file_might_use(spelling: str) -> None:
    payload = f"Date,Core CPI\n{spelling},0.28\n"
    [point] = clevelandfed_nowcast_csv(payload, _provider(), _target())
    assert point.target_period.isoformat() == "2026-08-01"


def test_the_scale_is_config_not_code() -> None:
    """A figure published in percent has to become a fraction.

    Nothing downstream would notice a factor of a hundred — the scoreboard
    would simply report the Cleveland Fed as catastrophically wrong. The
    parser deliberately returns the raw figure and leaves the conversion to
    a stated, reviewable number in config/external.yaml.
    """
    [point] = clevelandfed_nowcast_csv("Date,Core CPI\n2026-08-01,0.28\n", _provider(), _target())
    assert point.raw_value == Decimal("0.28")
    assert point.raw_value * Decimal(str(_target().scale)) == Decimal("0.0028")

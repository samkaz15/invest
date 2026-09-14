"""Hand-typed consensus, and the unit error that would ruin the comparison.

A calendar prints three things that look alike and are not: a percent
change, a change in a level, and a level. The third is the dangerous one.
The unemployment rate is quoted as 4.3 and forecast by MIOS as a change, so
storing it unconverted records a consensus of "+4.3 percentage points" — not
wrong by a rounding error but by two orders of magnitude, and in the
direction that makes every human forecaster look catastrophically bad while
MIOS looks brilliant.

Most of this file is about refusing to guess when the unit and the target
disagree.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mios.config.loader import load_config
from mios.prediction.manual import (
    COLUMNS,
    ConsensusInputError,
    ConsensusRow,
    convert,
    read_rows,
)

REPO = Path(__file__).resolve().parents[2]
HEADER = ",".join(COLUMNS)
URL = "https://www.gaikaex.com/gaikaex/mark/calendar/"


def _targets() -> dict[str, object]:
    return load_config(REPO / "config").forecast.by_id()


def _row(series: str, value: str, unit: str) -> ConsensusRow:
    return ConsensusRow(
        target_series_id=series,
        target_period=date(2026, 9, 1),
        value=Decimal(value),
        unit=unit,
        observed_at=datetime(2026, 9, 25, 9, 0, tzinfo=UTC),
        source_url=URL,
        note="",
    )


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "consensus.csv"
    path.write_text(f"# a comment\n\n{HEADER}\n{body}", encoding="utf-8")
    return path


# ---------------------------------------------------------------- the file


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    """The shipped file is mostly instructions, and must still parse."""
    path = _write(
        tmp_path, f"ser_us_nfp_level,2026-09-01,175,level_change,2026-09-25T09:00:00Z,{URL},\n"
    )
    [row] = read_rows(path)
    assert row.value == Decimal("175")
    assert row.unit == "level_change"


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    """Nobody has typed anything yet is a normal state, not a failure."""
    assert read_rows(tmp_path / "nothing.csv") == []


def test_a_row_without_provenance_is_refused(tmp_path: Path) -> None:
    """指示書 §26: no figure without a source. A consensus nobody can trace
    is a number somebody remembered."""
    path = _write(tmp_path, "ser_us_nfp_level,2026-09-01,175,level_change,2026-09-25T09:00:00Z,,\n")
    with pytest.raises(ConsensusInputError, match="source_url"):
        read_rows(path)


def test_an_unknown_unit_is_refused_rather_than_assumed(tmp_path: Path) -> None:
    path = _write(
        tmp_path, f"ser_us_nfp_level,2026-09-01,175,thousands,2026-09-25T09:00:00Z,{URL},\n"
    )
    with pytest.raises(ConsensusInputError, match="unit must be one of"):
        read_rows(path)


def test_one_bad_row_rejects_the_whole_file(tmp_path: Path) -> None:
    """Silently dropping the line you just typed is worse than refusing to load.

    You would go on believing the number was recorded, and find out six
    months later that the comparison had a hole in it.
    """
    good = f"ser_us_nfp_level,2026-09-01,175,level_change,2026-09-25T09:00:00Z,{URL},\n"
    bad = f"ser_us_unemployment_rate,not-a-date,4.3,level,2026-09-25T09:00:00Z,{URL},\n"
    with pytest.raises(ConsensusInputError):
        read_rows(_write(tmp_path, good + bad))


def test_a_renamed_column_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "consensus.csv"
    path.write_text("series,period,value,unit,observed_at,source_url,note\n", encoding="utf-8")
    with pytest.raises(ConsensusInputError, match="header must be exactly"):
        read_rows(path)


# ------------------------------------------------------------- conversion


def test_a_percent_becomes_a_fraction() -> None:
    """A calendar prints 0.3; MIOS forecasts 0.003."""
    spec = _targets()["ser_us_core_cpi_index"]
    assert convert(_row("ser_us_core_cpi_index", "0.3", "percent_change"), spec, None) == Decimal(  # type: ignore[arg-type]
        "0.003"
    )


def test_a_level_change_passes_straight_through() -> None:
    """Payrolls are counted in thousands and quoted as a change, so +175k is
    already the number MIOS forecasts."""
    spec = _targets()["ser_us_nfp_level"]
    assert convert(_row("ser_us_nfp_level", "175", "level_change"), spec, None) == Decimal(175)  # type: ignore[arg-type]


def test_a_percent_handed_to_a_level_target_is_refused() -> None:
    """Converting would need a base nobody stated, so it raises instead.

    This is the error that produces a plausible-looking wrong answer rather
    than an obviously broken one.
    """
    spec = _targets()["ser_us_nfp_level"]
    with pytest.raises(ConsensusInputError, match="without assuming a base"):
        convert(_row("ser_us_nfp_level", "0.3", "percent_change"), spec, None)  # type: ignore[arg-type]


def test_a_level_handed_to_a_percent_target_is_refused() -> None:
    spec = _targets()["ser_us_core_cpi_index"]
    with pytest.raises(ConsensusInputError, match="must be 'percent_change'"):
        convert(_row("ser_us_core_cpi_index", "317.6", "level"), spec, None)  # type: ignore[arg-type]

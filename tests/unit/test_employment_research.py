"""Test point-in-time checks and precisely defined market observations."""

import csv
from datetime import timedelta
from pathlib import Path

import pytest
from ops.employment_research import build, instant, load_bars, observed_moves


def test_no_using_retrospective_dataset_as_prior_known_information() -> None:
    data = {"research_as_of": "2026-11-06T10:45:00Z", "records": []}
    with pytest.raises(ValueError, match="retrospective"):
        build(data, instant("2026-01-01T00:00:00Z"), {})


def test_exact_bar_horizons_and_gaps(tmp_path: Path) -> None:
    file = tmp_path / "bars.csv"
    start = instant("2026-10-02T12:30:00Z")
    with file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["symbol", "instrument_id", "bar_start", "open", "close", "source_url", "retrieved_at"]
        )
        for mins, close in [(0, "101"), (25, "102"), (55, "99")]:
            writer.writerow(
                [
                    "XAUUSD",
                    "TEST:GOLD",
                    (start + timedelta(minutes=mins)).isoformat(),
                    "100",
                    close,
                    "https://example.com/gold",
                    "2026-11-01T00:00:00Z",
                ]
            )
    bars = load_bars(file, instant("2026-11-06T00:00:00Z"))
    actual = observed_moves(bars, "XAUUSD", start)
    assert actual["5"]["change_percent"] == "1.00"
    assert actual["30"]["change_percent"] == "2.00"
    assert actual["60"]["change_percent"] == "-1.00"
    assert actual["1440"] is None
    assert all(v is None for v in observed_moves(bars, "USDJPY", start).values())
    # Prices acquired a month later are unavailable to an earlier as_of.
    assert not load_bars(file, instant("2026-10-03T00:00:00Z"))


def test_reject_bar_fetched_before_close(tmp_path: Path) -> None:
    file = tmp_path / "bars.csv"
    file.write_text(
        "symbol,instrument_id,bar_start,open,close,source_url,retrieved_at\n"
        "XAUUSD,TEST:GOLD,2026-10-02T12:30:00Z,1,1,https://example.com,"
        "2026-10-02T12:31:00Z\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="before its interval ends"):
        load_bars(file, instant("2026-11-06T00:00:00Z"))

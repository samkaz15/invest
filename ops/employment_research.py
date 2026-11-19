#!/usr/bin/env python3
"""Report first-print employment releases and optional 5-minute market observations.

This is retrospective research, not an executable trading strategy or forecast.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HORIZONS = (5, 30, 60, 1440)
ASSETS = ("USDJPY", "XAUUSD")


def instant(value: str) -> datetime:
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return t.astimezone(UTC)


def load_bars(path: Path, as_of: datetime) -> dict[tuple[str, datetime], dict[str, Any]]:
    """Read 5-minute bars; a bar is known only after its close and documented capture.

    CSV columns: symbol,instrument_id,bar_start,open,close,source_url,retrieved_at.
    An exact event-time bar is mandatory. No interpolation or forward fill.
    """
    result: dict[tuple[str, datetime], dict[str, Any]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = row["symbol"]
            start = instant(row["bar_start"])
            fetched = instant(row["retrieved_at"])
            if (
                symbol not in ASSETS
                or not row["source_url"].startswith("https://")
                or not row["instrument_id"].strip()
            ):
                raise ValueError("invalid symbol or source URL")
            if start.second or start.microsecond or start.minute % 5:
                raise ValueError("bar_start must align to 5-minute UTC boundary")
            if fetched < start + timedelta(minutes=5):
                raise ValueError("bar cannot be retrieved before its interval ends")
            try:
                opening, closing = Decimal(row["open"]), Decimal(row["close"])
            except InvalidOperation as exc:
                raise ValueError("invalid price") from exc
            if not opening.is_finite() or not closing.is_finite() or opening <= 0 or closing <= 0:
                raise ValueError("price must be finite and positive")
            key = (symbol, start)
            if key in result:
                raise ValueError("duplicate bar")
            # Retrospective observations cannot be used as information at a prior instant.
            if fetched <= as_of and start + timedelta(minutes=5) <= as_of:
                result[key] = {
                    "open": opening,
                    "close": closing,
                    "url": row["source_url"],
                    "instrument_id": row["instrument_id"],
                    "retrieved_at": fetched,
                }
    return result


def observed_moves(
    bars: dict[tuple[str, datetime], dict[str, Any]], symbol: str, event_at: datetime
) -> dict[str, Any]:
    baseline = bars.get((symbol, event_at))
    output: dict[str, Any] = {}
    for minutes in HORIZONS:
        end = bars.get((symbol, event_at + timedelta(minutes=minutes - 5)))
        if (
            baseline is None
            or end is None
            or (baseline["url"], baseline["instrument_id"]) != (end["url"], end["instrument_id"])
        ):
            output[str(minutes)] = None
        else:
            pct = (end["close"] / baseline["open"] - 1) * 100
            output[str(minutes)] = {
                "baseline_open": str(baseline["open"]),
                "end_close": str(end["close"]),
                "change_percent": str(pct),
                "source_url": end["url"],
                "instrument_id": end["instrument_id"],
                "baseline_retrieved_at": baseline["retrieved_at"].isoformat(),
                "end_retrieved_at": end["retrieved_at"].isoformat(),
            }
    return output


def build(
    data: dict[str, Any], as_of: datetime, bars: dict[tuple[str, datetime], dict[str, Any]]
) -> dict[str, Any]:
    if as_of < instant(data["research_as_of"]):
        raise ValueError("retrospective release dataset was not available at this as_of")
    output = []
    for item in data["records"]:
        release = instant(item["release_at"])
        if release > as_of:
            continue
        output.append(
            {
                **item,
                "nfp_surprise_thousands_retrospective": (
                    item["nfp_initial_thousands"] - item["reuters_consensus_thousands"]
                    if item["reuters_consensus_thousands"] is not None
                    else None
                ),
                "price_observations": {
                    symbol: observed_moves(bars, symbol, release) for symbol in ASSETS
                },
            }
        )
    return {
        "schema_version": "employment-research-report/v1",
        "as_of": as_of.isoformat(),
        "scope": "retrospective observation; not a forecast or trading signal",
        "consensus_warning": "historical media reports, not a contemporaneously captured vintage",
        "price_method": "event 5m opening price to closing price at horizon; no interpolation",
        "records": output,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--releases", type=Path, required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--prices", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        as_of = instant(args.as_of)
        data = json.loads(args.releases.read_text(encoding="utf-8"))
        bars = load_bars(args.prices, as_of) if args.prices else {}
        report = build(data, as_of, bars)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        p.exit(2, f"error: {exc}\n")
    print(f"{len(report['records'])} releases; {len(bars)} eligible bars; output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

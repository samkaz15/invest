"""Payload readers: one raw item -> observations for one series.

A parser is a pure function over text. It never fetches, never writes, and
never guesses: given a payload shape it does not recognise, it raises
:class:`ParseError` so the collector quarantines the item in the DLQ. That
matters more than it sounds — the failure mode this guards against is a
provider changing its response and the parser quietly returning zero
observations, which every layer above would read as "no new data" rather
than "we are broken" (CONSTITUTION.md Art.4-4).

The parsers here were written without network access, so their exact
expectations are documented inline and verified against live responses in
CI rather than asserted to be right.
"""

import csv
import io
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from mios.common.errors import MiosError
from mios.config.series import SeriesSpec


class ParseError(MiosError):
    """A payload could not be read as the shape its series expects."""


class ParsedPoint:
    """One (reference period, value) pair lifted out of a payload.

    ``value is None`` records that the publisher explicitly reported no
    figure for the period — distinct from the period being absent, which
    means we simply have not seen it.
    """

    __slots__ = ("observation_date", "value")

    def __init__(self, observation_date: date, value: Decimal | None) -> None:
        self.observation_date = observation_date
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ParsedPoint({self.observation_date.isoformat()}, {self.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ParsedPoint):
            return NotImplemented
        return self.observation_date == other.observation_date and self.value == other.value


Parser = Callable[[str, SeriesSpec], list[ParsedPoint]]


def _decimal(text: str, context: str) -> Decimal:
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ParseError(f"{context}: {text!r} is not a number") from exc


def _us_date(text: str, context: str) -> date:
    """MM/DD/YYYY, as the US Treasury writes it.

    Built as a ``date`` directly rather than via ``strptime``: a reference
    period is a calendar date, and routing it through a naive datetime would
    create exactly the ambiguous value the time discipline bans.
    """
    parts = text.split("/")
    if len(parts) != 3:
        raise ParseError(f"{context}: {text!r} is not a MM/DD/YYYY date")
    try:
        month, day, year = (int(p) for p in parts)
        return date(year, month, day)
    except ValueError as exc:
        raise ParseError(f"{context}: {text!r} is not a MM/DD/YYYY date") from exc


def _iso_date(text: str, context: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ParseError(f"{context}: {text!r} is not an ISO date") from exc


def _load_json(payload: str, context: str) -> object:
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ParseError(f"{context}: payload is not JSON: {exc}") from exc


def fred_json(payload: str, spec: SeriesSpec) -> list[ParsedPoint]:
    """FRED series/observations.

    Shape: ``{"observations": [{"date": "2026-08-01", "value": "325.1"}, ...]}``.
    FRED writes ``"."`` for a period it has no figure for, which is a real
    statement about the data and is preserved as a null value rather than
    dropped.
    """
    document = _load_json(payload, spec.series_id)
    if not isinstance(document, dict):
        raise ParseError(f"{spec.series_id}: FRED payload is not an object")
    if "error_message" in document:
        raise ParseError(f"{spec.series_id}: FRED error: {document['error_message']}")
    rows = document.get("observations")
    if not isinstance(rows, list):
        raise ParseError(
            f"{spec.series_id}: FRED payload has no 'observations' list (keys: {sorted(document)})"
        )

    points: list[ParsedPoint] = []
    for row in rows:
        if not isinstance(row, dict) or "date" not in row or "value" not in row:
            raise ParseError(f"{spec.series_id}: malformed FRED observation {row!r}")
        observation_date = _iso_date(str(row["date"]), spec.series_id)
        raw = str(row["value"]).strip()
        value = None if raw in (".", "") else _decimal(raw, f"{spec.series_id} {observation_date}")
        points.append(ParsedPoint(observation_date, value))
    return points


def treasury_csv(payload: str, spec: SeriesSpec) -> list[ParsedPoint]:
    """US Treasury daily par yield curve CSV.

    One CSV carries the whole curve, so ``provider_code`` is the column
    header for this series ("2 Yr", "10 Yr", ...). Dates come as
    MM/DD/YYYY. A missing cell is a null value: the Treasury does publish
    days where a tenor has no rate.
    """
    reader = csv.DictReader(io.StringIO(payload))
    if reader.fieldnames is None:
        raise ParseError(f"{spec.series_id}: Treasury CSV has no header row")
    headers = [h.strip() for h in reader.fieldnames]
    if spec.provider_code not in headers:
        raise ParseError(
            f"{spec.series_id}: column {spec.provider_code!r} not in Treasury CSV "
            f"(headers: {headers})"
        )
    date_header = next((h for h in headers if h.lower() == "date"), None)
    if date_header is None:
        raise ParseError(f"{spec.series_id}: Treasury CSV has no Date column (headers: {headers})")

    points: list[ParsedPoint] = []
    for row in reader:
        cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        raw_date = cleaned.get(date_header, "")
        if not raw_date:
            continue  # trailing blank line
        observation_date = _us_date(raw_date, spec.series_id)
        raw_value = cleaned.get(spec.provider_code, "")
        value = (
            None
            if raw_value in ("", "N/A")
            else _decimal(raw_value, f"{spec.series_id} {observation_date}")
        )
        points.append(ParsedPoint(observation_date, value))
    if not points:
        raise ParseError(f"{spec.series_id}: Treasury CSV contained no data rows")
    return points


def twelvedata_json(payload: str, spec: SeriesSpec) -> list[ParsedPoint]:
    """Twelve Data time_series (ADR-011).

    Shape: ``{"status": "ok", "values": [{"datetime": "2026-09-11",
    "close": "2412.30"}, ...]}``. The daily close is taken as the
    observation. Errors arrive as ``{"status": "error", "message": ...}``
    with HTTP 200, including rate-limit refusals — which is exactly the
    case that must not be mistaken for an empty result.
    """
    document = _load_json(payload, spec.series_id)
    if not isinstance(document, dict):
        raise ParseError(f"{spec.series_id}: Twelve Data payload is not an object")
    if document.get("status") == "error" or "code" in document:
        raise ParseError(
            f"{spec.series_id}: Twelve Data error {document.get('code')}: {document.get('message')}"
        )
    rows = document.get("values")
    if not isinstance(rows, list):
        raise ParseError(
            f"{spec.series_id}: Twelve Data payload has no 'values' list (keys: {sorted(document)})"
        )

    points: list[ParsedPoint] = []
    for row in rows:
        if not isinstance(row, dict) or "datetime" not in row or "close" not in row:
            raise ParseError(f"{spec.series_id}: malformed Twelve Data row {row!r}")
        stamp = str(row["datetime"])
        observation_date = _iso_date(stamp.split(" ")[0], spec.series_id)
        raw = str(row["close"]).strip()
        value = None if raw == "" else _decimal(raw, f"{spec.series_id} {observation_date}")
        points.append(ParsedPoint(observation_date, value))
    return points


PARSERS: dict[str, Parser] = {
    "fred_json": fred_json,
    "treasury_csv": treasury_csv,
    "twelvedata_json": twelvedata_json,
}


def get_parser(name: str) -> Parser:
    parser = PARSERS.get(name)
    if parser is None:
        raise ParseError(f"unknown parser {name!r} (registered: {sorted(PARSERS)})")
    return parser


def utc_midnight(day: date) -> datetime:
    """A reference date as a tz-aware instant, for comparisons against vintages."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)

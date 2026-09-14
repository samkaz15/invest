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
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from mios.common.errors import MiosError
from mios.config.series import SeriesSpec


class ParseError(MiosError):
    """A payload could not be read as the shape its series expects."""


@dataclass(frozen=True)
class ParsedPoint:
    """One (reference period, value) pair lifted out of a payload.

    ``value is None`` records that the publisher explicitly reported no
    figure for the period — distinct from the period being absent, which
    means we simply have not seen it.

    ``vintage_at`` is set only by feeds that actually know when a value
    became public: ALFRED does, a plain FRED or vendor response does not.
    When it is None the normalizer falls back to the fetch time, which is
    the earliest moment this system could have known — honest, if coarse.
    Inventing a publication time for a feed that does not report one would
    be fabricating provenance (CONSTITUTION.md Art.4).
    """

    observation_date: date
    value: Decimal | None
    vintage_at: datetime | None = None


Parser = Callable[[str, SeriesSpec], list[ParsedPoint]]


def utc_midnight(day: date) -> datetime:
    """A calendar date as a tz-aware instant at the start of that day."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


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


def alfred_json(payload: str, spec: SeriesSpec) -> list[ParsedPoint]:
    """ALFRED series/observations — FRED's archive, with real vintages.

    Same endpoint and payload shape as :func:`fred_json`, but requested
    across a range of realtime dates, so one response carries *every*
    vintage of every period rather than just the current one::

        {"observations": [
            {"realtime_start": "2026-09-11", "date": "2026-08-01", "value": "325.4"},
            {"realtime_start": "2026-10-13", "date": "2026-08-01", "value": "325.6"},
            ...]}

    ``realtime_start`` is when that figure became the published value, so
    it is used as the vintage directly. This is the difference between
    "MIOS first saw 325.4 when it polled" and "the BLS published 325.4 on
    the 11th" — and it is what makes a backtest of a period MIOS was not
    running for honest rather than approximate.

    Same-day granularity is all ALFRED offers: a vintage is a date, not a
    timestamp. It is read as UTC midnight, which places the value at the
    start of the day it became public. That errs toward *later* knowledge
    being hidden, never toward it leaking early.
    """
    document = _load_json(payload, spec.series_id)
    if not isinstance(document, dict):
        raise ParseError(f"{spec.series_id}: ALFRED payload is not an object")
    if "error_message" in document:
        raise ParseError(f"{spec.series_id}: ALFRED error: {document['error_message']}")
    rows = document.get("observations")
    if not isinstance(rows, list):
        raise ParseError(
            f"{spec.series_id}: ALFRED payload has no 'observations' list "
            f"(keys: {sorted(document)})"
        )

    points: list[ParsedPoint] = []
    for row in rows:
        if not isinstance(row, dict) or not {"date", "value", "realtime_start"} <= set(row):
            raise ParseError(
                f"{spec.series_id}: ALFRED row lacks date/value/realtime_start: {row!r}"
            )
        observation_date = _iso_date(str(row["date"]), spec.series_id)
        vintage = utc_midnight(_iso_date(str(row["realtime_start"]), spec.series_id))
        raw = str(row["value"]).strip()
        value = None if raw in (".", "") else _decimal(raw, f"{spec.series_id} {observation_date}")
        points.append(ParsedPoint(observation_date, value, vintage))
    return points


def mof_jgb_csv(payload: str, spec: SeriesSpec) -> list[ParsedPoint]:
    """Japan MOF daily JGB yields.

    The USDJPY chain needs the Japanese leg of the rate differential, and
    the MOF publishes it as a CSV whose header row names tenors in Japanese
    ("2年", "10年"), with dates in the Japanese era calendar (R8.9.11 =
    Reiwa 8). Both are handled here rather than being normalised upstream,
    because the raw store keeps exactly what the server sent.

    Reiwa began in 2019, so Reiwa N is 2018 + N. Only Reiwa is accepted: a
    future era change must fail loudly rather than silently produce dates
    decades off.

    UNVERIFIED against the live endpoint — see docs/ARCHITECTURE.md §6 A-3.
    A wrong guess surfaces as a collection failure, not as bad data.
    """
    reader = csv.reader(io.StringIO(payload))
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if not rows:
        raise ParseError(f"{spec.series_id}: MOF CSV is empty")

    header_index = next(
        (i for i, r in enumerate(rows) if any(c.strip() == spec.provider_code for c in r)),
        None,
    )
    if header_index is None:
        sample = [c.strip() for c in rows[0]][:12]
        raise ParseError(
            f"{spec.series_id}: tenor {spec.provider_code!r} not found in MOF CSV "
            f"(first row: {sample})"
        )
    header = [c.strip() for c in rows[header_index]]
    column = header.index(spec.provider_code)

    points: list[ParsedPoint] = []
    for row in rows[header_index + 1 :]:
        cells = [c.strip() for c in row]
        if not cells or not cells[0]:
            continue
        observation_date = _japanese_era_date(cells[0], spec.series_id)
        raw = cells[column] if column < len(cells) else ""
        value = None if raw in ("", "-") else _decimal(raw, f"{spec.series_id} {observation_date}")
        points.append(ParsedPoint(observation_date, value))
    if not points:
        raise ParseError(f"{spec.series_id}: MOF CSV contained no data rows")
    return points


_REIWA_EPOCH = 2018  # Reiwa 1 = 2019


def _japanese_era_date(text: str, context: str) -> date:
    """``R8.9.11`` -> 2026-09-11. Also accepts a plain ISO date."""
    if "-" in text:
        return _iso_date(text, context)
    body = text.upper().removeprefix("R")
    parts = body.split(".")
    if len(parts) != 3:
        raise ParseError(f"{context}: {text!r} is not an R<era>.<month>.<day> date")
    try:
        era_year, month, day = (int(p) for p in parts)
        return date(_REIWA_EPOCH + era_year, month, day)
    except ValueError as exc:
        raise ParseError(f"{context}: {text!r} is not an R<era>.<month>.<day> date") from exc


PARSERS: dict[str, Parser] = {
    "fred_json": fred_json,
    "alfred_json": alfred_json,
    "treasury_csv": treasury_csv,
    "twelvedata_json": twelvedata_json,
    "mof_jgb_csv": mof_jgb_csv,
}


def get_parser(name: str) -> Parser:
    parser = PARSERS.get(name)
    if parser is None:
        raise ParseError(f"unknown parser {name!r} (registered: {sorted(PARSERS)})")
    return parser

"""Other people's forecasts of the same targets, stored as vintages.

MIOS scores itself against a naive baseline, and that is the right first
question. It is also a low bar: doing nothing is beaten routinely, so
clearing it proves little. The question that decides whether this project
was worth building is whether it beat the number that was already public
and free on the same morning — and answering that needs the public number
captured at the moment it was knowable, and never rewritten.

Three rules shape this module, and each exists because its absence would
produce a flattering answer rather than an error.

**A row only when the figure changed.** The Cleveland Fed republishes its
file daily whether or not the nowcast moved. Writing a row per fetch would
make `published_at` mean "when we happened to look" and would fill the table
with duplicates that later look like a forecaster changing their mind every
day. Same discipline as observations, for the same reason.

**vintage_at is ours, published_at is theirs.** Backfilling a year of
history yields rows whose published_at is old and whose vintage_at is today.
Every leak-free read filters on vintage_at, so a backfill can never credit
MIOS with having known a forecast it had not yet fetched.

**The conversion is stated, and the raw figure is kept.** A nowcast
published as "0.28" meaning 0.28 percent has to become 0.0028 before it can
be compared with a MIOS point value. Nothing downstream would notice a
factor of a hundred — the scoreboard would simply report that the Cleveland
Fed is catastrophically bad at its own job. Storing raw_value beside the
converted one keeps that mistake findable after the fact.
"""

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from mios.common.errors import MiosError
from mios.common.ids import IdKind, make_dated_id, slugify
from mios.common.logutil import get_logger
from mios.config.external import ExternalConfig, ExternalTargetSpec, ProviderSpec
from mios.ingestion.rawstore import RawStore
from mios.storage.db import Database

logger = get_logger(__name__)


class ExternalParseError(MiosError):
    """The payload did not contain what the configuration said it would."""


@dataclass(frozen=True)
class ExternalPoint:
    """One forecast figure, as published."""

    target_period: date
    raw_value: Decimal
    #: When the publisher says this figure was produced. ``None`` when the
    #: payload carries no stamp, in which case the fetch time stands in —
    #: which is never earlier than the truth.
    published_at: datetime | None = None


# --------------------------------------------------------------------- parsers


def _month_start(text: str) -> date | None:
    """Read the several date spellings a forecast file might use."""
    raw = text.strip()
    if not raw:
        return None
    # Every forecast here is for a calendar month, so the day part is
    # discarded whichever spelling the file uses. Anything unrecognised
    # returns None and the row is skipped rather than guessed at.
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y", "%b %Y", "%B %Y"):
        try:
            parsed = datetime.strptime(raw, fmt)  # noqa: DTZ007 - a month, not an instant
        except ValueError:
            continue
        return date(parsed.year, parsed.month, 1)
    return None


def _decimal(text: str) -> Decimal | None:
    raw = text.strip().replace(",", "").replace("%", "")
    if raw in {"", "-", "--", "NA", "N/A", "."}:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def clevelandfed_nowcast_csv(
    payload: str, provider: ProviderSpec, target: ExternalTargetSpec
) -> list[ExternalPoint]:
    """A wide CSV: one row per month, one column per indicator.

    The failure this reader is built around is a renamed column. That is the
    likeliest way this breaks, it produces no exception on its own, and a
    reader that returned an empty list would be read upstream as "no new
    forecast today" — indefinitely. So a missing column raises, and the
    message names every column actually present, which turns a guess in
    config/external.yaml into a one-line fix after a single verify run.
    """
    try:
        rows = list(csv.DictReader(io.StringIO(payload)))
    except csv.Error as exc:
        raise ExternalParseError(f"{provider.provider_id}: unreadable CSV: {exc}") from exc
    if not rows:
        raise ExternalParseError(f"{provider.provider_id}: CSV contained no rows")

    columns = [c for c in list(rows[0]) if c is not None]
    if target.provider_code not in columns:
        raise ExternalParseError(
            f"{provider.provider_id}: no column {target.provider_code!r} for "
            f"{target.target_series_id}; columns present: {columns}"
        )
    date_column = next(
        (c for c in columns if c.strip().lower() in {"date", "month", "period", "reference month"}),
        None,
    )
    if date_column is None:
        raise ExternalParseError(
            f"{provider.provider_id}: no date column; columns present: {columns}"
        )

    points: list[ExternalPoint] = []
    for row in rows:
        period = _month_start(row.get(date_column) or "")
        if period is None:
            continue
        value = _decimal(row.get(target.provider_code) or "")
        if value is None:
            # A blank cell is a month they have not nowcast yet, which is a
            # real state and not an error.
            continue
        points.append(ExternalPoint(target_period=period, raw_value=value))

    if not points:
        raise ExternalParseError(
            f"{provider.provider_id}: column {target.provider_code!r} parsed "
            f"{len(rows)} row(s) but none carried a usable value"
        )
    return points


PARSERS: dict[str, Callable[[str, ProviderSpec, ExternalTargetSpec], list[ExternalPoint]]] = {
    "clevelandfed_nowcast_csv": clevelandfed_nowcast_csv,
}


def get_external_parser(
    name: str,
) -> Callable[[str, ProviderSpec, ExternalTargetSpec], list[ExternalPoint]]:
    try:
        return PARSERS[name]
    except KeyError:
        raise ExternalParseError(
            f"unknown external forecast parser {name!r}; known: {sorted(PARSERS)}"
        ) from None


# ------------------------------------------------------------------ repository


class ExternalForecastRepo:
    """Reads and writes ``external_forecasts``. No other module touches it."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def latest(
        self, provider_id: str, target_series_id: str, target_period: date
    ) -> dict[str, Any] | None:
        """The newest stored figure for one provider/target/period."""
        return self._db.query_one(
            """
            SELECT * FROM external_forecasts
            WHERE provider_id = %(p)s AND target_series_id = %(s)s AND target_period = %(d)s
            ORDER BY published_at DESC LIMIT 1
            """,
            {"p": provider_id, "s": target_series_id, "d": target_period},
        )

    def save(self, row: dict[str, Any]) -> bool:
        """Insert one forecast vintage. Never updates; duplicates are no-ops."""
        result = self._db.query_one(
            """
            INSERT INTO external_forecasts (external_forecast_id, provider_id,
                target_series_id, target_period, published_at, vintage_at, point_value,
                raw_value, raw_unit, tier, method, source_url, raw_item_id)
            VALUES (%(external_forecast_id)s, %(provider_id)s, %(target_series_id)s,
                %(target_period)s, %(published_at)s, %(vintage_at)s, %(point_value)s,
                %(raw_value)s, %(raw_unit)s, %(tier)s, %(method)s, %(source_url)s,
                %(raw_item_id)s)
            ON CONFLICT DO NOTHING
            RETURNING external_forecast_id
            """,
            row,
        )
        return result is not None

    def as_of(
        self, target_series_id: str, target_period: date, as_of: datetime
    ) -> list[dict[str, Any]]:
        """Each provider's newest forecast that MIOS could have known at ``as_of``.

        Filtered on vintage_at rather than published_at: the question is what
        MIOS had, not what existed somewhere in the world.
        """
        return self._db.query(
            """
            SELECT DISTINCT ON (provider_id) *
            FROM external_forecasts
            WHERE target_series_id = %(s)s AND target_period = %(d)s AND vintage_at <= %(a)s
            ORDER BY provider_id, vintage_at DESC
            """,
            {"s": target_series_id, "d": target_period, "a": as_of},
        )

    def unscored(self) -> list[dict[str, Any]]:
        return self._db.query(
            """
            SELECT f.* FROM external_forecasts f
            LEFT JOIN external_forecast_errors e USING (external_forecast_id)
            WHERE e.external_forecast_id IS NULL
            ORDER BY f.vintage_at
            """
        )


# ------------------------------------------------------------------ normalizer


@dataclass
class ExternalReport:
    """What an ingestion run did, including what it could not do."""

    raw_items: int = 0
    written: int = 0
    unchanged: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


class ExternalIngestor:
    """Raw payloads -> stored forecast vintages."""

    def __init__(
        self,
        store: RawStore,
        repo: ExternalForecastRepo,
        config: ExternalConfig,
        tiers: dict[str, int],
    ) -> None:
        self._store = store
        self._repo = repo
        self._config = config
        self._tiers = tiers

    def run(self) -> ExternalReport:
        report = ExternalReport()
        for provider in self._config.providers:
            for item in self._store.items(provider.provider_id):
                report.raw_items += 1
                for target in provider.targets:
                    self._ingest(provider, target, item, report)
        logger.info(
            "external: raw_items=%d written=%d unchanged=%d failures=%d",
            report.raw_items,
            report.written,
            report.unchanged,
            len(report.failures),
        )
        return report

    def _ingest(
        self,
        provider: ProviderSpec,
        target: ExternalTargetSpec,
        item: Any,
        report: ExternalReport,
    ) -> None:
        try:
            points = get_external_parser(provider.parser)(item.payload_text, provider, target)
        except ExternalParseError as exc:
            report.failures.append(str(exc))
            logger.error("external parse failed: %s", exc)
            return

        scale = Decimal(str(target.scale))
        for point in points:
            value = point.raw_value * scale
            previous = self._repo.latest(
                provider.provider_id, target.target_series_id, point.target_period
            )
            if previous is not None and Decimal(str(previous["point_value"])) == value:
                # Republished, unchanged. Writing it would turn "when this
                # figure first appeared" into "when we last looked".
                report.unchanged += 1
                continue

            published_at = point.published_at or item.retrieved_at
            slug = (
                f"{slugify(provider.provider_id.removeprefix('src_'))}-"
                f"{slugify(target.target_series_id.removeprefix('ser_'))}-"
                f"{point.target_period.isoformat()}"
            )
            written = self._repo.save(
                {
                    "external_forecast_id": make_dated_id(
                        IdKind.EXTERNAL_FORECAST, published_at.date().isoformat(), slug
                    ),
                    "provider_id": provider.provider_id,
                    "target_series_id": target.target_series_id,
                    "target_period": point.target_period,
                    "published_at": published_at,
                    "vintage_at": item.retrieved_at,
                    "point_value": value,
                    "raw_value": point.raw_value,
                    "raw_unit": target.raw_unit,
                    "tier": self._tiers.get(provider.provider_id, 4),
                    "method": provider.method,
                    "source_url": provider.source_url,
                    "raw_item_id": item.raw_item_id,
                }
            )
            if written:
                report.written += 1
            else:
                report.unchanged += 1
